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
from noetrium_platform.composition.research_os_value_authorities import (
    ResearchOSArtifactValueAuthority,
)
from noetrium_platform.composition.research_os_values import (
    ResearchOSValueAuthorityMissing,
    ResearchOSValueReference,
    ResearchOSValueRouter,
    ResearchOSValueSubject,
)
from noetrium_platform.evidence.artifact.catalog.providers import SQLiteArtifactRegistry
from noetrium_platform.evidence.artifact.content.providers import (
    DirectoryArtifactBlobStore,
)
from noetrium_platform.evidence.artifact.contracts import ArtifactContentIdentity
from noetrium_platform.evidence.artifact.lineage.relation.providers import (
    SQLiteArtifactLineageStore,
)
from noetrium_platform.evidence.artifact.retention.providers import (
    SQLiteArtifactRetentionStore,
)
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
from noetrium_platform.foundation.kernel.kernel import (
    JsonValue,
    canonical_digest,
    freeze_json,
)
from noetrium_platform.foundation.portfolio.runtime import SQLitePortfolioRevisionStore
from noetrium_platform.composition.research_os_graph import (
    compile_research_portfolio_graph,
)
from noetrium_platform.composition.research_os_migration import (
    ResearchOSExecutionCut,
)
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphControlPhase,
    ResearchGraphExecutionConflict,
    ResearchGraphLiveNodeState,
)
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

    def execute(
        self,
        context,
        node,
        lowering,
        inputs,
        *,
        execution_cut_id,
        deadline,
    ):
        del lowering, deadline
        assert len(execution_cut_id) == 64
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


def _bound(tmp_path: Path, runtime, values, *, artifact_lineage=None):
    revisions = SQLitePortfolioRevisionStore(tmp_path / "portfolio.sqlite3")
    blobs = DirectoryArtifactBlobStore(tmp_path / "blobs")
    graph = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    pool = _pool()
    control = StrictResearchOSControl(
        graph,
        pool,
        runtime,
        values,
        artifact_lineage=artifact_lineage,
    )
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


def test_quiescent_graph_control_pause_checkpoint_resume_drain_cancel(
    tmp_path: Path,
) -> None:
    runtime = _Runtime()
    values = ResearchOSValueRouter((_ValueAuthority(),))
    graph, pool, research_os = _bound(tmp_path, runtime, values)
    try:
        portfolio = _portfolio()
        revision = research_os.commit(portfolio, message="control")
        target = api.ResearchExecutionTarget("execution-control", revision)

        assert research_os.run(target).state == "succeeded"

        paused = research_os.pause(target)
        assert paused.state == "paused"
        assert paused.payload["control_phase"] == ResearchGraphControlPhase.PAUSED.value

        checkpointed = research_os.checkpoint(target)
        assert checkpointed.state == "checkpointed"
        assert len(checkpointed.payload["checkpoint_digest"]) == 64

        resumed = research_os.resume(target)
        assert resumed.state == "succeeded"

        drained = research_os.drain(target)
        assert drained.state == "paused"
        assert drained.payload["control_phase"] == ResearchGraphControlPhase.PAUSED.value

        cancelled = research_os.cancel(target)
        assert cancelled.state == "cancelled"
        assert cancelled.payload["control_phase"] == ResearchGraphControlPhase.CANCELLED.value

        inspected = research_os.inspect(target)
        assert inspected.state == "cancelled"
        assert inspected.payload["control_phase"] == ResearchGraphControlPhase.CANCELLED.value
        assert graph.control_state(inspected.payload["cut_id"]).phase is (
            ResearchGraphControlPhase.CANCELLED
        )
    finally:
        pool.close()


def test_running_interrupt_fences_attempt_and_requires_reconciliation(
    tmp_path: Path,
) -> None:
    runtime = _Runtime()
    values = ResearchOSValueRouter((_ValueAuthority(),))
    graph, pool, research_os = _bound(tmp_path, runtime, values)
    try:
        portfolio = _portfolio()
        revision = research_os.commit(portfolio, message="interrupt")
        target = api.ResearchExecutionTarget("execution-interrupt", revision)
        compilation = compile_research_portfolio_graph(revision, portfolio)
        cut = ResearchOSExecutionCut.from_compilation(
            target.execution_id,
            compilation,
        )
        graph.ensure_execution(cut.cut_id, compilation.plan)
        graph.move_active_cut(target.execution_id, cut.cut_id)

        graph.mark_ready(cut.cut_id, "paper::source", now_ns=1)
        claimed = graph.claim(
            cut.cut_id,
            "paper::source",
            owner_id="worker-a",
            now_ns=2,
            lease_expires_at_ns=100,
        )
        assert claimed.attempt_id is not None
        graph.mark_running(
            cut.cut_id,
            "paper::source",
            attempt_id=claimed.attempt_id,
            owner_id="worker-a",
            now_ns=3,
        )

        interrupted = research_os.interrupt(target)
        assert interrupted.state == "recovery_required"
        assert interrupted.payload["control_phase"] == (
            ResearchGraphControlPhase.RECOVERY_REQUIRED.value
        )
        snapshot = graph.snapshot(cut.cut_id)
        assert snapshot.node("paper::source").state is (
            ResearchGraphLiveNodeState.RECONCILE_REQUIRED
        )

        with pytest.raises(
            ResearchGraphExecutionConflict,
            match="cannot resume graph from control phase recovery_required",
        ):
            research_os.resume(target)

        with pytest.raises(
            ResearchGraphExecutionConflict,
            match="checkpoint",
        ):
            research_os.checkpoint(target)
    finally:
        pool.close()


def test_retry_and_reconcile_remain_proof_gated(tmp_path: Path) -> None:
    runtime = _Runtime()
    values = ResearchOSValueRouter((_ValueAuthority(),))
    _graph, pool, research_os = _bound(tmp_path, runtime, values)
    try:
        portfolio = _portfolio()
        revision = research_os.commit(portfolio, message="proof-gated-control")
        target = api.ResearchExecutionTarget("execution-proof-gated", revision)
        research_os.run(target)

        with pytest.raises(
            ResearchOSExecutionUnsupported,
            match="explicit ResearchNodeRef",
        ):
            research_os.retry(target)
        with pytest.raises(
            ResearchGraphExecutionConflict,
            match="definitively failed",
        ):
            research_os.retry(target.for_node("paper", "source"))
        with pytest.raises(
            ResearchOSExecutionUnsupported,
            match="explicit ResearchNodeRef",
        ):
            research_os.reconcile(target)
        with pytest.raises(
            ResearchOSExecutionUnsupported,
            match="no lower-authority reconciliation port",
        ):
            research_os.reconcile(target.for_node("paper", "source"))
    finally:
        pool.close()



class _ExecutionStoreWithoutActiveCut:
    def ensure_execution(self, execution_id, plan):
        raise AssertionError("unused")

    def snapshot(self, execution_id):
        raise AssertionError("unused")

    def recover_expired(self, execution_id, *, now_ns):
        raise AssertionError("unused")

    def mark_ready(self, execution_id, node_id, *, now_ns):
        raise AssertionError("unused")

    def claim(
        self,
        execution_id,
        node_id,
        *,
        owner_id,
        now_ns,
        lease_expires_at_ns,
    ):
        raise AssertionError("unused")

    def mark_running(
        self,
        execution_id,
        node_id,
        *,
        attempt_id,
        owner_id,
        now_ns,
    ):
        raise AssertionError("unused")

    def renew_lease(
        self,
        execution_id,
        node_id,
        *,
        attempt_id,
        owner_id,
        now_ns,
        lease_expires_at_ns,
    ):
        raise AssertionError("unused")

    def mark_succeeded(
        self,
        execution_id,
        node_id,
        *,
        attempt_id,
        owner_id,
        now_ns,
    ):
        raise AssertionError("unused")

    def mark_failed(
        self,
        execution_id,
        node_id,
        *,
        attempt_id,
        owner_id,
        now_ns,
        failure_type,
        failure_message,
    ):
        raise AssertionError("unused")

    def schedule_retry(
        self,
        execution_id,
        node_id,
        *,
        retry_not_before_ns,
    ):
        raise AssertionError("unused")

    def mark_blocked(
        self,
        execution_id,
        node_id,
        *,
        blocked_by_node_ids,
    ):
        raise AssertionError("unused")

    def resolve_reconciliation(
        self,
        execution_id,
        node_id,
        *,
        disposition,
        now_ns,
        retry_not_before_ns=None,
        failure_type=None,
        failure_message=None,
    ):
        raise AssertionError("unused")

    def mark_reused(
        self,
        execution_id,
        node_id,
        *,
        source_execution_id,
        source_node_id,
        semantic_digest,
        proof_digest,
        now_ns,
    ):
        raise AssertionError("unused")

    def reuse_record(self, execution_id, node_id):
        raise AssertionError("unused")

    def attempts(self, execution_id, node_id):
        raise AssertionError("unused")


def test_control_requires_explicit_active_cut_cas_authority() -> None:
    pool = _pool()
    try:
        with pytest.raises(TypeError, match="active-cut CAS store"):
            StrictResearchOSControl(
                _ExecutionStoreWithoutActiveCut(),
                pool,
                _Runtime(),
                ResearchOSValueRouter((_ValueAuthority(),)),
            )
    finally:
        pool.close()



class _ArtifactRuntime(_Runtime):
    def execute(
        self,
        context,
        node,
        lowering,
        inputs,
        *,
        execution_cut_id,
        deadline,
    ):
        del lowering, deadline
        context.checkpoint()
        self.executed.append(node.graph_node_id)
        if node.graph_node_id == "paper::source":
            return {"stage": "source"}
        if node.graph_node_id == "paper::derive":
            assert inputs["source"] == {"stage": "source"}
            return {"stage": "derived"}
        raise AssertionError(node.graph_node_id)


def _artifact_portfolio() -> api.ResearchPortfolio:
    builder = api.ResearchProgramBuilder("paper")
    builder.node(
        "source",
        kind=api.ResearchNodeKind.CUSTOM,
        outputs=(
            api.ResearchOutputSpec(
                "artifact",
                api.ResearchValueKind.ARTIFACT,
            ),
        ),
    )
    builder.node(
        "derive",
        kind=api.ResearchNodeKind.CUSTOM,
        outputs=(
            api.ResearchOutputSpec(
                "artifact",
                api.ResearchValueKind.ARTIFACT,
            ),
        ),
    )
    builder.depends(
        "derive",
        "source",
        bindings=(
            api.ResearchInputBinding(
                "source",
                "artifact",
                api.ResearchValueKind.ARTIFACT,
            ),
        ),
    )
    return api.ResearchPortfolio("suite", (builder.freeze(),))


def test_derived_artifact_requires_and_records_exact_lineage(tmp_path: Path) -> None:
    runtime = _ArtifactRuntime()
    blobs = DirectoryArtifactBlobStore(tmp_path / "artifact-blobs")
    registry = SQLiteArtifactRegistry(tmp_path / "artifact-catalog.sqlite3")
    retention = SQLiteArtifactRetentionStore(tmp_path / "artifact-retention.sqlite3")
    authority = ResearchOSArtifactValueAuthority(blobs, registry, retention)
    values = ResearchOSValueRouter((authority,))
    lineage = SQLiteArtifactLineageStore(tmp_path / "artifact-lineage.sqlite3")
    graph, pool, research_os = _bound(
        tmp_path,
        runtime,
        values,
        artifact_lineage=lineage,
    )
    try:
        portfolio = _artifact_portfolio()
        revision = research_os.commit(portfolio, message="artifact lineage")
        target = api.ResearchExecutionTarget("execution-artifact", revision)
        receipt = research_os.run(target)
        assert receipt.state == "succeeded"

        compilation = compile_research_portfolio_graph(revision, portfolio)
        cut_id = receipt.payload["cut_id"]
        source_node = compilation.node("paper::source")
        derive_node = compilation.node("paper::derive")
        source_ref = authority.lookup(
            ResearchOSValueSubject(
                cut_id,
                source_node.graph_node_id,
                "artifact",
                api.ResearchValueKind.ARTIFACT,
                source_node.semantic_digest,
            )
        )
        child_ref = authority.lookup(
            ResearchOSValueSubject(
                cut_id,
                derive_node.graph_node_id,
                "artifact",
                api.ResearchValueKind.ARTIFACT,
                derive_node.semantic_digest,
            )
        )
        assert source_ref.content_digest is not None
        assert child_ref.content_digest is not None
        child_identity = ArtifactContentIdentity(
            child_ref.authority_ref,
            child_ref.content_digest,
        )
        edges = lineage.parents(child_identity)
        assert len(edges) == 1
        assert edges[0].parent == ArtifactContentIdentity(
            source_ref.authority_ref,
            source_ref.content_digest,
        )
        assert edges[0].relation_type == "derived_from"
    finally:
        pool.close()


def test_derived_artifact_without_lineage_authority_fails_before_cut(tmp_path: Path) -> None:
    runtime = _ArtifactRuntime()
    authority = ResearchOSArtifactValueAuthority(
        DirectoryArtifactBlobStore(tmp_path / "artifact-blobs"),
        SQLiteArtifactRegistry(tmp_path / "artifact-catalog.sqlite3"),
        SQLiteArtifactRetentionStore(tmp_path / "artifact-retention.sqlite3"),
    )
    values = ResearchOSValueRouter((authority,))
    graph, pool, research_os = _bound(tmp_path, runtime, values)
    try:
        portfolio = _artifact_portfolio()
        revision = research_os.commit(portfolio, message="lineage missing")
        target = api.ResearchExecutionTarget("execution-lineage-missing", revision)
        with pytest.raises(
            ResearchOSExecutionUnsupported,
            match="ArtifactLineageRelationPort",
        ):
            research_os.run(target)
        assert graph.active_cut("execution-lineage-missing") is None
    finally:
        pool.close()
