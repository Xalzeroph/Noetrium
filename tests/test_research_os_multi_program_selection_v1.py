from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from noetrium import api
from noetrium_platform.product import research_os as research_os_api
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_os import bind_portfolio_research_os
from noetrium_platform.composition.research_os_execution import (
    ResearchOSNodeAdmission,
    StrictResearchOSControl,
)
from noetrium_platform.composition.research_os_values import (
    ResearchOSValueReference,
    ResearchOSValueRouter,
)
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
from noetrium_platform.foundation.kernel.kernel import (
    JsonValue,
    canonical_digest,
    freeze_json,
)
from noetrium_platform.foundation.portfolio.runtime import SQLitePortfolioRevisionStore
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphLiveNodeState,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


@dataclass
class _DataAuthority:
    authority_id: str = "data.authority"
    supported_kinds: frozenset[research_os_api.ResearchValueKind] = frozenset(
        {research_os_api.ResearchValueKind.DATA}
    )
    rows: dict[str, JsonValue] = field(default_factory=dict)

    def publish(self, subject, value):
        frozen = freeze_json(value)
        self.rows[subject.subject_digest] = frozen
        return ResearchOSValueReference(
            subject,
            self.authority_id,
            subject.subject_digest,
            canonical_digest(frozen),
        )

    def lookup(self, subject):
        value = self.rows[subject.subject_digest]
        return ResearchOSValueReference(
            subject,
            self.authority_id,
            subject.subject_digest,
            canonical_digest(value),
        )

    def resolve(self, reference):
        return self.rows[reference.authority_ref]

    def reuse_proof(self, reference):
        return canonical_digest(
            {
                "authority_id": self.authority_id,
                "reference_digest": reference.reference_digest,
            }
        )


class _Runtime:
    def __init__(self) -> None:
        self.admitted: list[str] = []
        self.executed: list[str] = []

    def admit(self, node, lowering):
        if node.graph_node_id == "paper-d::unrelated":
            raise RuntimeError("unrelated node must never be admitted")
        self.admitted.append(node.graph_node_id)
        return ResearchOSNodeAdmission(
            node.graph_node_id,
            node.semantic_digest,
            lowering.lowering_digest,
            canonical_digest(
                {
                    "runtime": "multi-program-selection",
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
        del lowering, execution_cut_id, deadline
        task_context.checkpoint()
        self.executed.append(node.graph_node_id)
        if node.graph_node_id == "paper-a::source":
            assert inputs == {}
            return {"value": 3}
        if node.graph_node_id == "paper-b::middle":
            assert inputs["source"] == {"value": 3}
            return {"value": inputs["source"]["value"] + 4}
        if node.graph_node_id == "paper-c::target":
            assert inputs["middle"] == {"value": 7}
            return {"value": inputs["middle"]["value"] * 2}
        raise AssertionError(node.graph_node_id)


def _portfolio() -> research_os_api.ResearchPortfolio:
    paper_a = research_os_api.ResearchProgramBuilder("paper-a")
    paper_a.node(
        "source",
        kind=research_os_api.ResearchNodeKind.CUSTOM,
        outputs=(research_os_api.ResearchOutputSpec("data", research_os_api.ResearchValueKind.DATA),),
    )

    paper_b = research_os_api.ResearchProgramBuilder("paper-b")
    paper_b.node(
        "middle",
        kind=research_os_api.ResearchNodeKind.CUSTOM,
        outputs=(research_os_api.ResearchOutputSpec("data", research_os_api.ResearchValueKind.DATA),),
    )

    paper_c = research_os_api.ResearchProgramBuilder("paper-c")
    paper_c.node(
        "target",
        kind=research_os_api.ResearchNodeKind.CUSTOM,
        outputs=(research_os_api.ResearchOutputSpec("data", research_os_api.ResearchValueKind.DATA),),
    )

    paper_d = research_os_api.ResearchProgramBuilder("paper-d")
    paper_d.node(
        "unrelated",
        kind=research_os_api.ResearchNodeKind.CUSTOM,
        outputs=(research_os_api.ResearchOutputSpec("data", research_os_api.ResearchValueKind.DATA),),
    )

    return research_os_api.ResearchPortfolio(
        "multi-paper",
        (
            paper_a.freeze(),
            paper_b.freeze(),
            paper_c.freeze(),
            paper_d.freeze(),
        ),
        (
            research_os_api.ResearchPortfolioDependency(
                research_os_api.ResearchNodeRef("paper-a", "source"),
                research_os_api.ResearchNodeRef("paper-b", "middle"),
                (
                    research_os_api.ResearchInputBinding(
                        "source",
                        "data",
                        research_os_api.ResearchValueKind.DATA,
                    ),
                ),
            ),
            research_os_api.ResearchPortfolioDependency(
                research_os_api.ResearchNodeRef("paper-b", "middle"),
                research_os_api.ResearchNodeRef("paper-c", "target"),
                (
                    research_os_api.ResearchInputBinding(
                        "middle",
                        "data",
                        research_os_api.ResearchValueKind.DATA,
                    ),
                ),
            ),
        ),
    )


def _pool() -> ResearchExecutionPool:
    return ResearchExecutionPool(
        orchestration_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=4,
            max_cpu_workers=1,
            max_async_io_in_flight=4,
        )
    )


def test_node_scoped_run_closes_transitive_cross_program_dependencies_only(
    tmp_path: Path,
) -> None:
    runtime = _Runtime()
    values = ResearchOSValueRouter((_DataAuthority(),))
    graph = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    pool = _pool()
    control = StrictResearchOSControl(graph, pool, runtime, values)
    research_os = bind_portfolio_research_os(
        SQLitePortfolioRevisionStore(tmp_path / "portfolio.sqlite3"),
        __import__(
            "noetrium_platform.evidence.artifact.content.providers",
            fromlist=["DirectoryArtifactBlobStore"],
        ).DirectoryArtifactBlobStore(tmp_path / "blobs"),
        control=control,
    )
    try:
        portfolio = _portfolio()
        revision = research_os.commit(portfolio, message="cross-program selection")
        target = research_os_api.ResearchExecutionTarget("multi-paper-execution", revision)

        receipt = research_os.run(target.for_node("paper-c", "target"))

        assert receipt.state == "succeeded"
        assert receipt.payload["selected_node_ids"] == (
            "paper-a::source",
            "paper-b::middle",
            "paper-c::target",
        )
        assert runtime.admitted == [
            "paper-a::source",
            "paper-b::middle",
            "paper-c::target",
        ]
        assert runtime.executed == [
            "paper-a::source",
            "paper-b::middle",
            "paper-c::target",
        ]

        active = graph.active_cut(target.execution_id)
        assert active is not None
        snapshot = graph.snapshot(active.cut_id)
        assert snapshot.node("paper-a::source").state is ResearchGraphLiveNodeState.SUCCEEDED
        assert snapshot.node("paper-b::middle").state is ResearchGraphLiveNodeState.SUCCEEDED
        assert snapshot.node("paper-c::target").state is ResearchGraphLiveNodeState.SUCCEEDED
        assert snapshot.node("paper-d::unrelated").state is ResearchGraphLiveNodeState.PENDING
        assert graph.attempts(active.cut_id, "paper-d::unrelated") == ()
    finally:
        pool.close()
