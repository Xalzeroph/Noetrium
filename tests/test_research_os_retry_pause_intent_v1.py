from __future__ import annotations

from pathlib import Path

from noetrium import api
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_os import bind_portfolio_research_os
from noetrium_platform.composition.research_os_execution import (
    ResearchOSNodeAdmission,
    StrictResearchOSControl,
)
from noetrium_platform.composition.research_os_values import ResearchOSValueRouter
from noetrium_platform.evidence.artifact.content.providers import (
    DirectoryArtifactBlobStore,
)
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.portfolio.runtime import SQLitePortfolioRevisionStore
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphLiveNodeState,
    ResearchGraphNodeControlPhase,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


class _FailOnceRuntime:
    def __init__(self) -> None:
        self.execute_calls = 0

    def admit(self, node, lowering):
        return ResearchOSNodeAdmission(
            node.graph_node_id,
            node.semantic_digest,
            lowering.lowering_digest,
            canonical_digest(
                {
                    "runtime": "retry-pause-intent",
                    "node": node.graph_node_id,
                }
            ),
        )

    def execute(
        self,
        context,
        task_context,
        node,
        lowering,
        inputs,
        *,
        execution_cut_id,
        deadline,
    ):
        del node, lowering, inputs, execution_cut_id, deadline
        task_context.checkpoint()
        context.checkpoint()
        self.execute_calls += 1
        if self.execute_calls == 1:
            raise RuntimeError("synthetic first-attempt failure")
        return None


def _pool() -> ResearchExecutionPool:
    return ResearchExecutionPool(
        orchestration_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_cpu_workers=1,
            max_async_io_in_flight=2,
        )
    )


def _portfolio() -> api.ResearchPortfolio:
    builder = api.ResearchProgramBuilder("paper")
    builder.node(
        "task",
        kind=api.ResearchNodeKind.CUSTOM,
    )
    return api.ResearchPortfolio("retry-pause", (builder.freeze(),))


def test_retry_respects_local_pause_until_explicit_resume(tmp_path: Path) -> None:
    graph = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    pool = _pool()
    runtime = _FailOnceRuntime()
    research_os = bind_portfolio_research_os(
        SQLitePortfolioRevisionStore(tmp_path / "portfolio.sqlite3"),
        DirectoryArtifactBlobStore(tmp_path / "blobs"),
        control=StrictResearchOSControl(
            graph,
            pool,
            runtime,
            ResearchOSValueRouter(()),
        ),
    )
    try:
        portfolio = _portfolio()
        revision = research_os.commit(portfolio, message="retry pause")
        target = api.ResearchExecutionTarget("retry-pause-execution", revision)
        node_target = target.for_node("paper", "task")

        first = research_os.run(node_target)
        assert first.state == "failed"
        active = graph.active_cut(target.execution_id)
        assert active is not None
        first_record = graph.snapshot(active.cut_id).node("paper::task")
        assert runtime.execute_calls == 1, (
            first_record.failure_type,
            first_record.failure_message,
            first.payload,
        )
        assert first_record.state is ResearchGraphLiveNodeState.FAILED

        paused = research_os.pause(node_target)
        assert paused.state == "node_paused"
        assert paused.payload["node"]["control_phase"] == (
            ResearchGraphNodeControlPhase.PAUSED.value
        )

        staged = research_os.retry(node_target)
        assert staged.state == "retry_staged"
        assert staged.payload["retry_root_control_phase"] == (
            ResearchGraphNodeControlPhase.PAUSED.value
        )
        assert runtime.execute_calls == 1
        assert graph.snapshot(active.cut_id).node("paper::task").state is (
            ResearchGraphLiveNodeState.RETRY_WAIT
        )
        assert graph.node_control_state(
            active.cut_id,
            "paper::task",
        ).phase is ResearchGraphNodeControlPhase.PAUSED
        assert len(graph.attempts(active.cut_id, "paper::task")) == 1

        resumed = research_os.resume(node_target)
        assert resumed.state == "succeeded"
        assert runtime.execute_calls == 2
        assert graph.snapshot(active.cut_id).node("paper::task").state is (
            ResearchGraphLiveNodeState.SUCCEEDED
        )
        assert len(graph.attempts(active.cut_id, "paper::task")) == 2
    finally:
        pool.close()
