from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from noetrium import api
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_os import bind_portfolio_research_os
from noetrium_platform.composition.research_os_execution import (
    ResearchOSExecutionUnsupported,
    ResearchOSNodeAdmission,
    StrictResearchOSControl,
)
from noetrium_platform.composition.research_os_values import (
    ResearchOSValueAuthorityMissing,
    ResearchOSValueReference,
    ResearchOSValueRouter,
)
from noetrium_platform.evidence.artifact.content.providers import (
    DirectoryArtifactBlobStore,
)
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
from noetrium_platform.foundation.kernel.kernel import (
    JsonValue,
    canonical_digest,
    freeze_json,
)
from noetrium_platform.foundation.portfolio.runtime import SQLitePortfolioRevisionStore
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


@dataclass
class _ValueAuthority:
    authority_id: str = "data.authority"
    supported_kinds: frozenset[api.ResearchValueKind] = frozenset(
        {api.ResearchValueKind.DATA}
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
    def __init__(self, *, reject: frozenset[str] = frozenset()) -> None:
        self.reject = reject
        self.executed: list[str] = []

    def admit(self, node, lowering):
        if node.graph_node_id in self.reject:
            raise RuntimeError(f"runtime rejected: {node.graph_node_id}")
        return ResearchOSNodeAdmission(
            node.graph_node_id,
            node.semantic_digest,
            lowering.lowering_digest,
            canonical_digest(
                {
                    "runtime": "test",
                    "graph_node_id": node.graph_node_id,
                }
            ),
        )

    def execute(self, context, node, lowering, inputs, *, deadline):
        del lowering, deadline
        context.checkpoint()
        self.executed.append(node.graph_node_id)
        if node.graph_node_id == "paper::source":
            return {"value": 7}
        if node.graph_node_id == "paper::consume":
            return {"seen": inputs["source"]["value"]}
        raise AssertionError(node.graph_node_id)


def _portfolio() -> api.ResearchPortfolio:
    builder = api.ResearchProgramBuilder("paper")
    builder.node(
        "source",
        kind=api.ResearchNodeKind.CUSTOM,
        outputs=(
            api.ResearchOutputSpec("data", api.ResearchValueKind.DATA),
        ),
    )
    builder.node(
        "consume",
        kind=api.ResearchNodeKind.CUSTOM,
        outputs=(
            api.ResearchOutputSpec("result", api.ResearchValueKind.DATA),
        ),
    )
    builder.depends(
        "consume",
        "source",
        bindings=(
            api.ResearchInputBinding(
                "source",
                "data",
                api.ResearchValueKind.DATA,
            ),
        ),
    )
    return api.ResearchPortfolio("suite", (builder.freeze(),))


def _pool() -> ResearchExecutionPool:
    return ResearchExecutionPool(
        orchestration_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_cpu_workers=1,
            max_async_io_in_flight=2,
        )
    )


def _bound(tmp_path: Path, runtime, values):
    revisions = SQLitePortfolioRevisionStore(tmp_path / "portfolio.sqlite3")
    blobs = DirectoryArtifactBlobStore(tmp_path / "blobs")
    graph = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    pool = _pool()
    control = StrictResearchOSControl(graph, pool, runtime, values)
    return (
        graph,
        pool,
        bind_portfolio_research_os(
            revisions,
            blobs,
            control=control,
        ),
    )


def test_public_run_closes_preflight_before_creating_durable_cut(tmp_path: Path) -> None:
    runtime = _Runtime()
    values = ResearchOSValueRouter((_ValueAuthority(),))
    graph, pool, research_os = _bound(tmp_path, runtime, values)
    try:
        portfolio = _portfolio()
        revision = research_os.commit(portfolio, message="run")
        target = api.ResearchExecutionTarget("execution-1", revision)

        receipt = research_os.run(target)
        assert receipt.state == "succeeded"
        assert runtime.executed == ["paper::source", "paper::consume"]

        active = graph.active_cut("execution-1")
        assert active is not None
        assert receipt.payload["cut_id"] == active.cut_id

        inspected = research_os.inspect(target)
        assert inspected.state == "durable"
        assert inspected.payload["cut_id"] == active.cut_id
        assert inspected.payload["states"]["succeeded"] == (
            "paper::consume",
            "paper::source",
        )
    finally:
        pool.close()


def test_runtime_admission_failure_creates_no_execution_cut(tmp_path: Path) -> None:
    runtime = _Runtime(reject=frozenset({"paper::consume"}))
    values = ResearchOSValueRouter((_ValueAuthority(),))
    graph, pool, research_os = _bound(tmp_path, runtime, values)
    try:
        portfolio = _portfolio()
        revision = research_os.commit(portfolio, message="reject")
        target = api.ResearchExecutionTarget("execution-reject", revision)

        with pytest.raises(RuntimeError, match="runtime rejected"):
            research_os.run(target)

        assert graph.active_cut("execution-reject") is None
    finally:
        pool.close()


def test_missing_value_authority_fails_before_cut_creation(tmp_path: Path) -> None:
    runtime = _Runtime()
    values = ResearchOSValueRouter(())
    graph, pool, research_os = _bound(tmp_path, runtime, values)
    try:
        portfolio = _portfolio()
        revision = research_os.commit(portfolio, message="missing authority")
        target = api.ResearchExecutionTarget("execution-missing", revision)

        with pytest.raises(ResearchOSValueAuthorityMissing):
            research_os.run(target)

        assert graph.active_cut("execution-missing") is None
    finally:
        pool.close()


def test_node_scoped_run_and_implicit_global_payload_fail_closed(tmp_path: Path) -> None:
    runtime = _Runtime()
    values = ResearchOSValueRouter((_ValueAuthority(),))
    _graph, pool, research_os = _bound(tmp_path, runtime, values)
    try:
        portfolio = _portfolio()
        revision = research_os.commit(portfolio, message="strict")
        target = api.ResearchExecutionTarget("execution-strict", revision)

        with pytest.raises(ResearchOSExecutionUnsupported, match="node-scoped RUN"):
            research_os.run(target.for_node("paper", "source"))

        with pytest.raises(ResearchOSExecutionUnsupported, match="root-input"):
            research_os.run(target, payload={"implicit": True})
    finally:
        pool.close()


def test_unimplemented_control_action_fails_closed(tmp_path: Path) -> None:
    runtime = _Runtime()
    values = ResearchOSValueRouter((_ValueAuthority(),))
    _graph, pool, research_os = _bound(tmp_path, runtime, values)
    try:
        portfolio = _portfolio()
        revision = research_os.commit(portfolio, message="control")
        target = api.ResearchExecutionTarget("execution-control", revision)

        with pytest.raises(
            ResearchOSExecutionUnsupported,
            match="no canonical durable implementation",
        ):
            research_os.pause(target)
    finally:
        pool.close()
