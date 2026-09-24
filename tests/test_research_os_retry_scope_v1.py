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
    ResearchGraphControlPhase,
    ResearchGraphLiveNodeState,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


class _FailOnceRuntime:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self._root_failures = 0

    def admit(self, node, lowering):
        return ResearchOSNodeAdmission(
            node.graph_node_id,
            node.semantic_digest,
            lowering.lowering_digest,
            canonical_digest(
                {
                    "runtime": "retry-scope",
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
        del lowering, inputs, execution_cut_id, deadline
        task_context.checkpoint()
        self.calls.append(node.graph_node_id)
        if node.graph_node_id == "paper::root" and self._root_failures == 0:
            self._root_failures += 1
            raise RuntimeError("root failed once")
        return None


def _portfolio() -> api.ResearchPortfolio:
    builder = api.ResearchProgramBuilder("paper")
    builder.node("root", kind=api.ResearchNodeKind.CUSTOM)
    builder.node("child", kind=api.ResearchNodeKind.CUSTOM)
    builder.node("unrelated", kind=api.ResearchNodeKind.CUSTOM)
    builder.depends("child", "root")
    return api.ResearchPortfolio("retry-scope", (builder.freeze(),))


def _pool() -> ResearchExecutionPool:
    return ResearchExecutionPool(
        orchestration_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=3,
            max_cpu_workers=1,
            max_async_io_in_flight=3,
        )
    )


def _bound(tmp_path: Path):
    graph = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    runtime = _FailOnceRuntime()
    pool = _pool()
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
    return graph, runtime, pool, research_os


def _fail_root_once(graph, runtime, research_os):
    portfolio = _portfolio()
    revision = research_os.commit(portfolio, message="retry scope")
    target = api.ResearchExecutionTarget("retry-execution", revision)
    research_os.run(target.for_node("paper", "root"))
    active = graph.active_cut(target.execution_id)
    assert active is not None
    snapshot = graph.snapshot(active.cut_id)
    assert snapshot.node("paper::root").state is ResearchGraphLiveNodeState.FAILED
    assert snapshot.node("paper::child").state is ResearchGraphLiveNodeState.PENDING
    assert snapshot.node("paper::unrelated").state is ResearchGraphLiveNodeState.PENDING
    assert runtime.calls == ["paper::root"]
    return target, active.cut_id


def test_retry_runs_only_affected_subgraph_and_required_ancestors(
    tmp_path: Path,
) -> None:
    graph, runtime, pool, research_os = _bound(tmp_path)
    try:
        target, cut_id = _fail_root_once(graph, runtime, research_os)

        receipt = research_os.retry(target.for_node("paper", "root"))

        assert receipt.state == "succeeded"
        assert receipt.payload["selected_node_ids"] == (
            "paper::child",
            "paper::root",
        )
        assert runtime.calls == [
            "paper::root",
            "paper::root",
            "paper::child",
        ]
        snapshot = graph.snapshot(cut_id)
        assert snapshot.node("paper::root").state is ResearchGraphLiveNodeState.SUCCEEDED
        assert snapshot.node("paper::child").state is ResearchGraphLiveNodeState.SUCCEEDED
        assert snapshot.node("paper::unrelated").state is ResearchGraphLiveNodeState.PENDING
        assert graph.attempts(cut_id, "paper::unrelated") == ()
    finally:
        pool.close()


def test_retry_on_globally_paused_graph_stages_without_resuming(
    tmp_path: Path,
) -> None:
    graph, runtime, pool, research_os = _bound(tmp_path)
    try:
        target, cut_id = _fail_root_once(graph, runtime, research_os)
        paused = research_os.pause(target)
        assert paused.state == "paused"
        assert paused.payload["control_phase"] == ResearchGraphControlPhase.PAUSED.value

        receipt = research_os.retry(target.for_node("paper", "root"))

        assert receipt.state == "retry_staged"
        assert receipt.payload["control_phase"] == ResearchGraphControlPhase.PAUSED.value
        assert receipt.payload["retry_root_node_id"] == "paper::root"
        assert receipt.payload["retry_descendant_node_ids"] == ("paper::child",)
        assert runtime.calls == ["paper::root"]

        snapshot = graph.snapshot(cut_id)
        assert snapshot.node("paper::root").state is ResearchGraphLiveNodeState.RETRY_WAIT
        assert snapshot.node("paper::child").state is ResearchGraphLiveNodeState.PENDING
        assert snapshot.node("paper::unrelated").state is ResearchGraphLiveNodeState.PENDING
        assert graph.control_state(cut_id).phase is ResearchGraphControlPhase.PAUSED
        assert len(graph.attempts(cut_id, "paper::root")) == 1
        assert graph.attempts(cut_id, "paper::child") == ()
        assert graph.attempts(cut_id, "paper::unrelated") == ()
    finally:
        pool.close()
