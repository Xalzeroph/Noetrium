from __future__ import annotations

from resource_test_support import make_execution_pool

from tests._execution_graph_fixtures import materialize_execution as _materialize_execution

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from noetrium_platform.product.research_control import ResearchExecutionTarget
from noetrium_platform.foundation.kernel.structure import (
    GraphStorageKind,
    NoetriumUnit,
    boundary_unit,
    endpoint_unit,
    port_unit,
    relation_unit,
    structure_unit,
    type_unit,
)
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_control import RootResearchControl
from noetrium_platform.composition.research_checkpoint import (
    ResearchNodeCheckpointProof,
)
from noetrium_platform.composition.research_checkpoint_store import (
    DirectoryResearchGraphCheckpointStore,
)
from noetrium_platform.composition.research_execution import (
    ResearchExecutionUnsupported,
    ResearchNodeAdmission,
    StrictResearchControl,
)
from noetrium_platform.composition.research_value_authorities import (
    ResearchImmutableValueAuthority,
)
from noetrium_platform.composition.research_values import (
    ResearchValueAuthorityMissing,
    ResearchValueReference,
    ResearchValueRouter,
    ResearchValueSubject,
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
    MachineCut,
    canonical_digest,
    freeze_json,
)
from noetrium_platform.foundation.portfolio.runtime import SQLitePortfolioRevisionStore
from noetrium_platform.composition.research_execution_graph import (
    compile_research_portfolio_graph,
)
from noetrium_platform.composition.research_execution_migration import (
    ResearchExecutionCut,
)
from noetrium_platform.composition.research_reconciliation import (
    ResearchNodeReconciliationProof,
)
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphAttemptState,
    ResearchGraphControlPhase,
    ResearchGraphExecutionConflict,
    ResearchGraphExecutionNotFound,
    ResearchGraphLiveNodeState,
    ResearchGraphNodeControlPhase,
    ResearchGraphReconciliationDisposition,
)
from noetrium_platform.research.execution.graph.providers import (
    SQLiteResearchGraphExecutionStore,
)


@dataclass
class _ValueAuthority:
    authority_id: str = "data.authority"
    supported_kinds: frozenset[GraphStorageKind] = frozenset(
        {GraphStorageKind.DATA}
    )
    rows: dict[str, JsonValue] = field(default_factory=dict)
    released: list[str] = field(default_factory=list)

    def publish(self, subject, value):
        frozen = freeze_json(value)
        self.rows[subject.subject_digest] = frozen
        return ResearchValueReference(
            subject,
            self.authority_id,
            subject.subject_digest,
            canonical_digest(frozen),
        )

    def lookup(self, subject):
        value = self.rows[subject.subject_digest]
        return ResearchValueReference(
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

    def release_execution(self, subject):
        self.released.append(subject.subject_digest)
        return canonical_digest(
            {
                "authority_id": self.authority_id,
                "released_subject_digest": subject.subject_digest,
            }
        )


class _Runtime:
    def __init__(self, *, reject: frozenset[str] = frozenset()) -> None:
        self.reject = reject
        self.executed: list[str] = []

    def admit(self, node, lowering):
        if node.graph_node_id in self.reject:
            raise RuntimeError(f"runtime rejected: {node.graph_node_id}")
        return ResearchNodeAdmission(
            node.graph_node_id,
            node.semantic_digest,
            lowering.binding_digest,
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
        task_context,
        node,
        lowering,
        inputs,
        *,
        execution_cut_id,
        deadline,
    ):
        del lowering, deadline
        assert len(execution_cut_id) == 64
        task_context.checkpoint()
        self.executed.append(node.graph_node_id)
        if node.graph_node_id == "paper::source":
            return {"value": 7}
        if node.graph_node_id == "paper::consume":
            return {"seen": inputs["source"]["value"]}
        raise AssertionError(node.graph_node_id)

    def checkpoint_node(
        self,
        node,
        lowering,
        *,
        execution_cut_id,
        attempt_id,
    ):
        commit_id = canonical_digest(
            {
                "test-checkpoint": execution_cut_id,
                "graph_node_id": node.graph_node_id,
                "binding_digest": lowering.binding_digest,
                "attempt_id": attempt_id,
            }
        )
        cut = MachineCut(
            machine_id=f"test:{node.graph_node_id}",
            revision=1,
            commit_id=commit_id,
            state_digest=canonical_digest({"node": node.graph_node_id}),
            unit_digest=canonical_digest(
                {"binding_digest": lowering.binding_digest}
            ),
            execution_lock_digest=canonical_digest(
                {
                    "binding_digest": lowering.binding_digest,
                    "runtime": "test",
                }
            ),
        )
        return ResearchNodeCheckpointProof(
            execution_cut_id,
            node.graph_node_id,
            node.semantic_digest,
            lowering.binding_digest,
            "test-machine-journal",
            cut,
            (commit_id,),
        )


class _ExecutionFailureRuntime(_Runtime):
    def __init__(
        self,
        *,
        reject: frozenset[str] = frozenset(),
        fail_execute: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__(reject=reject)
        self.fail_execute = fail_execute

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
        if node.graph_node_id in self.fail_execute:
            raise RuntimeError(f"execution failed: {node.graph_node_id}")
        return super().execute(
            context,
            task_context,
            node,
            lowering,
            inputs,
            execution_cut_id=execution_cut_id,
            deadline=deadline,
        )


class _ReconciliationRuntime(_Runtime):
    def reconcile_node(
        self,
        node,
        lowering,
        *,
        execution_cut_id,
        attempt_id,
    ):
        evidence = canonical_digest(
            {
                "test-reconcile": execution_cut_id,
                "node": node.graph_node_id,
                "attempt_id": attempt_id,
            }
        )
        return ResearchNodeReconciliationProof(
            execution_cut_id,
            node.graph_node_id,
            node.semantic_digest,
            lowering.binding_digest,
            attempt_id,
            ResearchGraphReconciliationDisposition.RETRY,
            "test-lower-authority",
            (evidence,),
        )


def _portfolio() -> NoetriumUnit:
    data_type = type_unit("research.data", GraphStorageKind.DATA)
    source = structure_unit(
        "source",
        traits=("research.runtime",),
        boundary=boundary_unit(
            outputs=(port_unit("data", data_type),),
        ),
    )
    consume = structure_unit(
        "consume",
        traits=("research.runtime",),
        boundary=boundary_unit(
            inputs=(port_unit("source", data_type),),
            outputs=(port_unit("result", data_type),),
        ),
    )
    flow = relation_unit(
        (endpoint_unit("source", "data"),),
        (endpoint_unit("consume", "source"),),
        "research.flow",
    )
    return structure_unit(
        "paper",
        traits=("research.portfolio",),
        members=(source, consume),
        relations=(flow,),
    )


def _portfolio_v2() -> NoetriumUnit:
    data_type = type_unit("research.data", GraphStorageKind.DATA)
    source = structure_unit(
        "source",
        traits=("research.runtime",),
        parameters={"revision": 2},
        boundary=boundary_unit(
            outputs=(port_unit("data", data_type),),
        ),
    )
    consume = structure_unit(
        "consume",
        traits=("research.runtime",),
        boundary=boundary_unit(
            inputs=(port_unit("source", data_type),),
            outputs=(port_unit("result", data_type),),
        ),
    )
    flow = relation_unit(
        (endpoint_unit("source", "data"),),
        (endpoint_unit("consume", "source"),),
        "research.flow",
    )
    return structure_unit(
        "paper",
        traits=("research.portfolio",),
        members=(source, consume),
        relations=(flow,),
    )


def _pool(*, exclusive_owner_generation: bool = False) -> ResearchExecutionPool:
    return make_execution_pool(
        orchestration_concurrency_budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_cpu_workers=1,
            max_async_io_in_flight=2,
        ),
        exclusive_owner_generation=exclusive_owner_generation,
    )


def _bound(
    tmp_path: Path,
    runtime,
    values,
    *,
    artifact_lineage=None,
    exclusive_owner_generation: bool = False,
):
    revisions = SQLitePortfolioRevisionStore(tmp_path / "portfolio.sqlite3")
    blobs = DirectoryArtifactBlobStore(tmp_path / "blobs")
    graph = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    pool = _pool(exclusive_owner_generation=exclusive_owner_generation)
    control = StrictResearchControl(
        graph,
        pool,
        runtime,
        values,
        artifact_lineage=artifact_lineage,
        checkpoints=DirectoryResearchGraphCheckpointStore(
            tmp_path / "graph-checkpoints"
        ),
    )
    return (
        graph,
        pool,
        RootResearchControl(
            revisions,
            blobs,
            control=control,
        ),
    )


def test_public_run_closes_preflight_before_creating_durable_cut(tmp_path: Path) -> None:
    runtime = _Runtime()
    values = ResearchValueRouter((_ValueAuthority(),))
    graph, pool, research = _bound(tmp_path, runtime, values)
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="run")
        target = ResearchExecutionTarget("execution-1", revision)

        receipt = research.run(target)
        assert receipt.state == "succeeded"
        assert runtime.executed == ["paper::source", "paper::consume"]

        active = graph.active_cut("execution-1")
        assert active is not None
        assert receipt.payload["cut_id"] == active.cut_id

        inspected = research.inspect(target)
        assert inspected.state == "durable"
        assert inspected.payload["cut_id"] == active.cut_id
        assert inspected.payload["states"]["succeeded"] == (
            "paper::consume",
            "paper::source",
        )
    finally:
        pool.close()


def test_exact_target_preflight_is_single_flight_and_run_reuses_it(
    tmp_path: Path,
) -> None:
    class CountingRuntime(_Runtime):
        def __init__(self) -> None:
            super().__init__()
            self.admit_count = 0

        def admit(self, node, lowering):
            self.admit_count += 1
            return super().admit(node, lowering)

    runtime = CountingRuntime()
    values = ResearchValueRouter((_ValueAuthority(),))
    revisions = SQLitePortfolioRevisionStore(tmp_path / "portfolio.sqlite3")
    blobs = DirectoryArtifactBlobStore(tmp_path / "blobs")
    graph = SQLiteResearchGraphExecutionStore(tmp_path / "graph.sqlite3")
    pool = _pool()
    strict = StrictResearchControl(
        graph,
        pool,
        runtime,
        values,
        checkpoints=DirectoryResearchGraphCheckpointStore(
            tmp_path / "graph-checkpoints"
        ),
    )
    research = RootResearchControl(revisions, blobs, control=strict)
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="single-preflight")
        target = ResearchExecutionTarget("execution-single-preflight", revision)

        first = strict.prepare(target, portfolio)
        admitted = runtime.admit_count
        assert admitted == len(first.selected_node_ids)

        second = strict.prepare(target, portfolio)
        assert second is first
        assert runtime.admit_count == admitted

        receipt = research.run(target)
        assert receipt.state == "succeeded"
        assert runtime.admit_count == admitted
    finally:
        pool.close()


def test_public_run_is_admitted_through_fleet_domain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _Runtime()
    values = ResearchValueRouter((_ValueAuthority(),))
    _graph, pool, research = _bound(tmp_path, runtime, values)
    observed: list[tuple[str, str | None, str | None]] = []
    original = pool.open_fleet_group

    def open_fleet_group(group_id: str, **kwargs):
        observed.append(
            (
                group_id,
                kwargs.get("tenant_id"),
                kwargs.get("resource_id"),
            )
        )
        return original(group_id, **kwargs)

    monkeypatch.setattr(pool, "open_fleet_group", open_fleet_group)
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="fleet-admission")
        target = ResearchExecutionTarget(
            "execution-fleet-admission",
            revision,
        )

        receipt = research.run(target)

        assert receipt.state == "succeeded"
        assert len(observed) == 1
        group_id, tenant_id, resource_id = observed[0]
        assert group_id.startswith("research-fleet:paper:execution-fleet-admission:")
        assert tenant_id == "paper"
        assert resource_id == "research-fleet:execution-fleet-admission"
        admission = pool.fleet_admission_snapshot()
        assert admission.admitted_total == 1
        assert admission.rejected_total == 0
    finally:
        pool.close()


def test_run_cannot_switch_active_revision_without_explicit_migration(
    tmp_path: Path,
) -> None:
    runtime = _Runtime()
    values = ResearchValueRouter((_ValueAuthority(),))
    graph, pool, research = _bound(tmp_path, runtime, values)
    try:
        first_portfolio = _portfolio()
        first_revision = research.commit(first_portfolio, message="r1")
        first_target = ResearchExecutionTarget("execution-revision", first_revision)
        research.run(first_target.for_graph(("paper", "source")))
        active_before = graph.active_cut(first_target.execution_id)
        assert active_before is not None

        second_portfolio = _portfolio_v2()
        second_revision = research.commit(
            second_portfolio,
            parents=(first_revision,),
            message="r2",
        )
        second_target = ResearchExecutionTarget(
            first_target.execution_id,
            second_revision,
        )
        second_compilation = compile_research_portfolio_graph(
            second_revision,
            second_portfolio,
        )
        second_cut = ResearchExecutionCut.from_compilation(
            second_target.execution_id,
            second_compilation,
        )

        with pytest.raises(
            ResearchGraphExecutionConflict,
            match="explicit migration",
        ):
            research.run(second_target.for_graph(("paper", "source")))

        assert graph.active_cut(first_target.execution_id) == active_before
        with pytest.raises(ResearchGraphExecutionNotFound):
            graph.snapshot(second_cut.cut_id)
    finally:
        pool.close()



def test_run_hot_replaces_quiescent_paused_revision_under_exclusive_owner_fence(
    tmp_path: Path,
) -> None:
    runtime = _Runtime()
    values = ResearchValueRouter((_ValueAuthority(),))
    graph, pool, research = _bound(
        tmp_path, runtime, values, exclusive_owner_generation=True
    )
    try:
        first_portfolio = _portfolio()
        first_revision = research.commit(first_portfolio, message="r1")
        execution_id = "execution-hot-replace"
        first_target = ResearchExecutionTarget(
            execution_id, first_revision
        )
        assert (
            research.run(first_target.for_graph(("paper", "source"))).state
            == "succeeded"
        )
        paused = research.pause(first_target)
        assert paused.state == "paused"
        first_active = graph.active_cut(execution_id)
        assert first_active is not None
        first_snapshot = graph.snapshot(first_active.cut_id)

        second_portfolio = _portfolio_v2()
        second_revision = research.commit(
            second_portfolio,
            parents=(first_revision,),
            message="r2",
        )
        second_target = ResearchExecutionTarget(
            execution_id, second_revision
        )
        receipt = research.run(second_target.for_graph(("paper", "source")))

        second_compilation = compile_research_portfolio_graph(
            second_revision, second_portfolio
        )
        second_cut = ResearchExecutionCut.from_compilation(
            execution_id, second_compilation, generation=2
        )
        active = graph.active_cut(execution_id)
        assert active is not None
        assert active.cut_id == second_cut.cut_id
        assert receipt.state == "succeeded"
        assert graph.snapshot(first_active.cut_id) == first_snapshot
        assert graph.control_state(first_active.cut_id).phase is (
            ResearchGraphControlPhase.PAUSED
        )
    finally:
        pool.close()


def test_run_supersedes_abandoned_revision_under_exclusive_owner_fence(
    tmp_path: Path,
) -> None:
    runtime = _Runtime()
    values = ResearchValueRouter((_ValueAuthority(),))
    graph, pool, research = _bound(
        tmp_path, runtime, values, exclusive_owner_generation=True
    )
    try:
        first_portfolio = _portfolio()
        first_revision = research.commit(first_portfolio, message="r1")
        first_target = ResearchExecutionTarget(
            "execution-abandoned-revision", first_revision
        )
        first_compilation = compile_research_portfolio_graph(
            first_revision, first_portfolio
        )
        first_cut = ResearchExecutionCut.from_compilation(
            first_target.execution_id, first_compilation
        )
        _materialize_execution(graph, first_cut.cut_id, first_compilation.execution_unit)
        graph.move_active_cut(first_target.execution_id, first_cut.cut_id)
        graph.mark_ready(first_cut.cut_id, "paper::source", now_ns=1)
        claimed = graph.claim(
            first_cut.cut_id,
            "paper::source",
            owner_id="research-graph-scheduler:dead-generation:worker",
            now_ns=2,
            lease_expires_at_ns=10_000,
        )
        graph.mark_running(
            first_cut.cut_id,
            "paper::source",
            attempt_id=claimed.attempt_id or "",
            owner_id="research-graph-scheduler:dead-generation:worker",
            now_ns=3,
        )

        second_portfolio = _portfolio_v2()
        second_revision = research.commit(
            second_portfolio, parents=(first_revision,), message="r2"
        )
        second_target = ResearchExecutionTarget(
            first_target.execution_id, second_revision
        )
        receipt = research.run(second_target.for_graph(("paper", "source")))

        second_compilation = compile_research_portfolio_graph(
            second_revision, second_portfolio
        )
        second_cut = ResearchExecutionCut.from_compilation(
            second_target.execution_id, second_compilation, generation=2
        )
        active = graph.active_cut(second_target.execution_id)
        assert active is not None
        assert active.cut_id == second_cut.cut_id
        assert receipt.state == "succeeded"
        assert graph.snapshot(first_cut.cut_id).node("paper::source").state is (
            ResearchGraphLiveNodeState.RECONCILE_REQUIRED
        )
        assert graph.control_state(first_cut.cut_id).phase is (
            ResearchGraphControlPhase.RECOVERY_REQUIRED
        )
        assert graph.snapshot(second_cut.cut_id).node("paper::source").state is (
            ResearchGraphLiveNodeState.SUCCEEDED
        )
    finally:
        pool.close()

def test_node_scoped_preflight_does_not_admit_unselected_nodes(tmp_path: Path) -> None:
    runtime = _Runtime(reject=frozenset({"paper::consume"}))
    values = ResearchValueRouter((_ValueAuthority(),))
    graph, pool, research = _bound(tmp_path, runtime, values)
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="selection admission")
        target = ResearchExecutionTarget("execution-selection-admission", revision)

        receipt = research.run(target.for_graph(("paper", "source")))
        assert receipt.state == "succeeded"
        assert receipt.payload["selected_node_ids"] == ("paper::source",)
        assert runtime.executed == ["paper::source"]

        active = graph.active_cut(target.execution_id)
        assert active is not None
        with pytest.raises(KeyError):
            graph.snapshot(active.cut_id).node("paper::consume")
        with pytest.raises(RuntimeError, match="runtime rejected: paper::consume"):
            research.run(target)
        with pytest.raises(KeyError):
            graph.attempts(active.cut_id, "paper::consume")
    finally:
        pool.close()


def test_runtime_admission_failure_creates_no_execution_cut(tmp_path: Path) -> None:
    runtime = _Runtime(reject=frozenset({"paper::consume"}))
    values = ResearchValueRouter((_ValueAuthority(),))
    graph, pool, research = _bound(tmp_path, runtime, values)
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="reject")
        target = ResearchExecutionTarget("execution-reject", revision)

        with pytest.raises(RuntimeError, match="runtime rejected"):
            research.run(target)

        assert graph.active_cut("execution-reject") is None
    finally:
        pool.close()


def test_missing_value_authority_fails_before_cut_creation(tmp_path: Path) -> None:
    runtime = _Runtime()
    values = ResearchValueRouter(())
    graph, pool, research = _bound(tmp_path, runtime, values)
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="missing authority")
        target = ResearchExecutionTarget("execution-missing", revision)

        with pytest.raises(ResearchValueAuthorityMissing):
            research.run(target)

        assert graph.active_cut("execution-missing") is None
    finally:
        pool.close()


def test_node_scoped_run_uses_dependency_closed_selection(tmp_path: Path) -> None:
    runtime = _Runtime()
    values = ResearchValueRouter((_ValueAuthority(),))
    graph, pool, research = _bound(tmp_path, runtime, values)
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="node selection")
        target = ResearchExecutionTarget("execution-selection", revision)

        source_receipt = research.run(target.for_graph(("paper", "source")))
        assert source_receipt.state == "succeeded"
        assert source_receipt.payload["selected_node_ids"] == ("paper::source",)
        assert runtime.executed == ["paper::source"]
        active = graph.active_cut(target.execution_id)
        assert active is not None
        snapshot = graph.snapshot(active.cut_id)
        assert snapshot.node("paper::source").state is ResearchGraphLiveNodeState.SUCCEEDED
        with pytest.raises(KeyError):
            snapshot.node("paper::consume")
        with pytest.raises(KeyError):
            graph.attempts(active.cut_id, "paper::consume")

        consume_receipt = research.run(target.for_graph(("paper", "consume")))
        assert consume_receipt.state == "succeeded"
        assert consume_receipt.payload["selected_node_ids"] == (
            "paper::consume",
            "paper::source",
        )
        assert runtime.executed == ["paper::source", "paper::consume"]
        snapshot = graph.snapshot(active.cut_id)
        assert snapshot.node("paper::consume").state is ResearchGraphLiveNodeState.SUCCEEDED

        with pytest.raises(
            ResearchExecutionUnsupported,
            match="does not identify exactly one",
        ):
            research.run(target.for_graph(("paper", "missing")))
        with pytest.raises(ResearchExecutionUnsupported, match="root-input"):
            research.run(target, payload={"implicit": True})
    finally:
        pool.close()


def test_quiescent_graph_control_pause_checkpoint_resume_drain_cancel(
    tmp_path: Path,
) -> None:
    runtime = _Runtime()
    authority = _ValueAuthority()
    values = ResearchValueRouter((authority,))
    graph, pool, research = _bound(tmp_path, runtime, values)
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="control")
        target = ResearchExecutionTarget("execution-control", revision)

        assert research.run(target).state == "succeeded"

        paused = research.pause(target)
        assert paused.state == "paused"
        assert paused.payload["control_phase"] == ResearchGraphControlPhase.PAUSED.value

        checkpointed = research.checkpoint(target)
        assert checkpointed.state == "checkpointed"
        assert len(checkpointed.payload["checkpoint_digest"]) == 64

        resumed = research.resume(target)
        assert resumed.state == "succeeded"

        drained = research.drain(target)
        assert drained.state == "paused"
        assert drained.payload["control_phase"] == ResearchGraphControlPhase.PAUSED.value

        cancelled = research.cancel(target)
        assert cancelled.state == "cancelled"
        assert cancelled.payload["control_phase"] == ResearchGraphControlPhase.CANCELLED.value
        assert len(cancelled.payload["value_release_proof_digests"]) == 2
        assert len(authority.released) == 2

        inspected = research.inspect(target)
        assert inspected.state == "cancelled"
        assert inspected.payload["control_phase"] == ResearchGraphControlPhase.CANCELLED.value
        assert graph.control_state(inspected.payload["cut_id"]).phase is (
            ResearchGraphControlPhase.CANCELLED
        )
    finally:
        pool.close()


def test_resume_admission_failure_preserves_paused_control(tmp_path: Path) -> None:
    runtime = _Runtime()
    values = ResearchValueRouter((_ValueAuthority(),))
    graph, pool, research = _bound(tmp_path, runtime, values)
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="resume-preflight")
        target = ResearchExecutionTarget("execution-resume-preflight", revision)
        assert research.run(target).state == "succeeded"
        assert research.pause(target).state == "paused"

        active = graph.active_cut(target.execution_id)
        assert active is not None
        paused = graph.control_state(active.cut_id)
        assert paused.phase is ResearchGraphControlPhase.PAUSED

        runtime.reject = frozenset({"paper::consume"})
        with pytest.raises(RuntimeError, match="runtime rejected: paper::consume"):
            research.resume(target)

        after = graph.control_state(active.cut_id)
        assert after.phase is ResearchGraphControlPhase.PAUSED
        assert after.generation == paused.generation
    finally:
        pool.close()


def test_node_pause_inspect_and_resume_preserve_graph_wide_activity(
    tmp_path: Path,
) -> None:
    runtime = _Runtime()
    values = ResearchValueRouter((_ValueAuthority(),))
    graph, pool, research = _bound(tmp_path, runtime, values)
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="node pause")
        target = ResearchExecutionTarget("execution-node-pause", revision)
        # Materialize the immutable cut without executing the target node.
        research.run(target.for_graph(("paper", "source")))
        active = graph.active_cut(target.execution_id)
        assert active is not None
        # consume remains pending and is independently controllable.
        consume = target.for_graph(("paper", "consume"))
        paused = research.pause(consume)
        assert paused.state == "node_paused"
        assert paused.payload["node"]["control_phase"] == (
            ResearchGraphNodeControlPhase.PAUSED.value
        )
        assert paused.payload["control_phase"] == ResearchGraphControlPhase.ACTIVE.value

        inspected = research.inspect(consume)
        assert inspected.payload["node"]["state"] == ResearchGraphLiveNodeState.PENDING.value
        assert inspected.payload["node"]["control_phase"] == (
            ResearchGraphNodeControlPhase.PAUSED.value
        )

        resumed = research.resume(consume)
        assert resumed.state == "succeeded"
        assert runtime.executed == ["paper::source", "paper::consume"]
        assert graph.control_state(active.cut_id).phase is ResearchGraphControlPhase.ACTIVE
    finally:
        pool.close()


def test_node_interrupt_claimed_before_start_can_resume_without_reconciliation(
    tmp_path: Path,
) -> None:
    runtime = _Runtime()
    values = ResearchValueRouter((_ValueAuthority(),))
    graph, pool, research = _bound(tmp_path, runtime, values)
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="node claimed interrupt")
        target = ResearchExecutionTarget("execution-node-claimed", revision)
        compilation = compile_research_portfolio_graph(revision, portfolio)
        cut = ResearchExecutionCut.from_compilation(target.execution_id, compilation)
        _materialize_execution(graph, cut.cut_id, compilation.execution_unit)
        graph.move_active_cut(target.execution_id, cut.cut_id)
        graph.mark_ready(cut.cut_id, "paper::source", now_ns=1)
        graph.claim(
            cut.cut_id,
            "paper::source",
            owner_id="worker-a",
            now_ns=2,
            lease_expires_at_ns=9_000_000_000_000_000_000,
        )

        interrupted = research.interrupt(target.for_graph(("paper", "source")))
        assert interrupted.state == "node_paused"
        assert interrupted.payload["node"]["state"] == ResearchGraphLiveNodeState.PENDING.value
        assert interrupted.payload["node"]["control_phase"] == (
            ResearchGraphNodeControlPhase.PAUSED.value
        )
        assert interrupted.payload["control_phase"] == ResearchGraphControlPhase.ACTIVE.value

        resumed = research.resume(target.for_graph(("paper", "source")))
        assert resumed.state == "succeeded"
        assert runtime.executed == ["paper::source"]
    finally:
        pool.close()


def test_node_running_interrupt_reconciles_locally_then_remains_paused(
    tmp_path: Path,
) -> None:
    runtime = _ReconciliationRuntime()
    values = ResearchValueRouter((_ValueAuthority(),))
    graph, pool, research = _bound(tmp_path, runtime, values)
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="node local recovery")
        target = ResearchExecutionTarget("execution-node-recovery", revision)
        compilation = compile_research_portfolio_graph(revision, portfolio)
        cut = ResearchExecutionCut.from_compilation(target.execution_id, compilation)
        _materialize_execution(graph, cut.cut_id, compilation.execution_unit)
        graph.move_active_cut(target.execution_id, cut.cut_id)
        graph.mark_ready(cut.cut_id, "paper::source", now_ns=1)
        claim = graph.claim(
            cut.cut_id,
            "paper::source",
            owner_id="worker-a",
            now_ns=2,
            lease_expires_at_ns=9_000_000_000_000_000_000,
        )
        graph.mark_running(
            cut.cut_id,
            "paper::source",
            attempt_id=claim.attempt_id or "",
            owner_id="worker-a",
            now_ns=3,
        )

        interrupted = research.interrupt(target.for_graph(("paper", "source")))
        assert interrupted.state == "node_recovery_required"
        assert interrupted.payload["node"]["state"] == (
            ResearchGraphLiveNodeState.RECONCILE_REQUIRED.value
        )
        assert interrupted.payload["node"]["control_phase"] == (
            ResearchGraphNodeControlPhase.RECOVERY_REQUIRED.value
        )
        assert interrupted.payload["control_phase"] == ResearchGraphControlPhase.ACTIVE.value

        reconciled = research.reconcile(target.for_graph(("paper", "source")))
        assert reconciled.payload["reconciliation_disposition"] == "retry"
        assert reconciled.payload["node_control_phase"] == (
            ResearchGraphNodeControlPhase.PAUSED.value
        )
        assert graph.control_state(cut.cut_id).phase is ResearchGraphControlPhase.ACTIVE
        assert graph.snapshot(cut.cut_id).node("paper::source").state is (
            ResearchGraphLiveNodeState.RETRY_WAIT
        )
        assert graph.node_control_state(cut.cut_id, "paper::source").phase is (
            ResearchGraphNodeControlPhase.PAUSED
        )

        resumed = research.resume(target.for_graph(("paper", "source")))
        assert resumed.state == "succeeded"
    finally:
        pool.close()


def test_node_cancel_atomically_cancels_descendants_only(tmp_path: Path) -> None:
    runtime = _Runtime()
    values = ResearchValueRouter((_ValueAuthority(),))
    graph, pool, research = _bound(tmp_path, runtime, values)
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="node cancel")
        target = ResearchExecutionTarget("execution-node-cancel", revision)
        compilation = compile_research_portfolio_graph(revision, portfolio)
        cut = ResearchExecutionCut.from_compilation(target.execution_id, compilation)
        _materialize_execution(graph, cut.cut_id, compilation.execution_unit)
        graph.move_active_cut(target.execution_id, cut.cut_id)

        cancelled = research.cancel(target.for_graph(("paper", "source")))
        assert cancelled.state == "node_cancelled"
        assert cancelled.payload["node"]["state"] == ResearchGraphLiveNodeState.CANCELLED.value
        assert cancelled.payload["node"]["control_phase"] == (
            ResearchGraphNodeControlPhase.CANCELLED.value
        )
        assert cancelled.payload["cancelled_descendant_node_ids"] == ("paper::consume",)
        snapshot = graph.snapshot(cut.cut_id)
        assert snapshot.node("paper::source").state is ResearchGraphLiveNodeState.CANCELLED
        assert snapshot.node("paper::consume").state is ResearchGraphLiveNodeState.CANCELLED
        assert graph.control_state(cut.cut_id).phase is ResearchGraphControlPhase.ACTIVE

        report = research.run(target)
        assert report.state == "cancelled"
        assert report.payload["cancelled_node_ids"] == (
            "paper::consume",
            "paper::source",
        )
        assert runtime.executed == []
    finally:
        pool.close()


def test_node_scoped_checkpoint_binds_exact_lower_machine_cut(
    tmp_path: Path,
) -> None:
    runtime = _Runtime()
    values = ResearchValueRouter((_ValueAuthority(),))
    graph, pool, research = _bound(tmp_path, runtime, values)
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="node checkpoint")
        target = ResearchExecutionTarget("execution-node-checkpoint", revision)
        research.run(target.for_graph(("paper", "source")))

        receipt = research.checkpoint(target.for_graph(("paper", "source")))
        assert receipt.state == "checkpointed"
        assert receipt.payload["checkpoint_node_ids"] == ("paper::source",)
        node = receipt.payload["checkpoint_nodes"][0]
        assert node["graph_node_id"] == "paper::source"
        assert node["authority_id"] == "test-machine-journal"
        assert len(node["machine_cut_digest"]) == 64
        assert len(node["checkpoint_proof_digest"]) == 64

        active = graph.active_cut(target.execution_id)
        assert active is not None
        with pytest.raises(KeyError):
            graph.snapshot(active.cut_id).node("paper::consume")
    finally:
        pool.close()


def test_running_interrupt_fences_attempt_and_requires_reconciliation(
    tmp_path: Path,
) -> None:
    runtime = _Runtime()
    values = ResearchValueRouter((_ValueAuthority(),))
    graph, pool, research = _bound(tmp_path, runtime, values)
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="interrupt")
        target = ResearchExecutionTarget("execution-interrupt", revision)
        compilation = compile_research_portfolio_graph(revision, portfolio)
        cut = ResearchExecutionCut.from_compilation(
            target.execution_id,
            compilation,
        )
        _materialize_execution(graph, cut.cut_id, compilation.execution_unit)
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

        interrupted = research.interrupt(target)
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
            research.resume(target)

        with pytest.raises(
            ResearchGraphExecutionConflict,
            match="checkpoint",
        ):
            research.checkpoint(target)
    finally:
        pool.close()


def test_graph_wide_reconcile_settles_recovery_frontier(tmp_path: Path) -> None:
    runtime = _ReconciliationRuntime()
    values = ResearchValueRouter((_ValueAuthority(),))
    graph, pool, research = _bound(tmp_path, runtime, values)
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="graph-wide-reconcile")
        target = ResearchExecutionTarget("execution-graph-wide-reconcile", revision)
        compilation = compile_research_portfolio_graph(revision, portfolio)
        cut = ResearchExecutionCut.from_compilation(target.execution_id, compilation)
        _materialize_execution(graph, cut.cut_id, compilation.execution_unit)
        graph.move_active_cut(target.execution_id, cut.cut_id)
        graph.mark_ready(cut.cut_id, "paper::source", now_ns=1)
        claimed = graph.claim(
            cut.cut_id,
            "paper::source",
            owner_id="worker-a",
            now_ns=2,
            lease_expires_at_ns=100,
        )
        graph.mark_running(
            cut.cut_id,
            "paper::source",
            attempt_id=claimed.attempt_id or "",
            owner_id="worker-a",
            now_ns=3,
        )
        interrupted = research.interrupt(target)
        assert interrupted.state == "recovery_required"

        reconciled = research.reconcile(target)

        assert reconciled.state == "reconciled"
        assert reconciled.payload["reconciled_node_ids"] == ("paper::source",)
        assert len(reconciled.payload["reconciliation_proofs"]) == 1
        assert reconciled.payload["reconciliation_proofs"][0]["disposition"] == "retry"
        assert graph.snapshot(cut.cut_id).reconciliation_required_node_ids == ()
        assert graph.snapshot(cut.cut_id).node("paper::source").state is (
            ResearchGraphLiveNodeState.RETRY_WAIT
        )
        assert graph.control_state(cut.cut_id).phase is ResearchGraphControlPhase.PAUSED
    finally:
        pool.close()


def test_active_retry_admission_failure_preserves_failed_attempt(tmp_path: Path) -> None:
    runtime = _ExecutionFailureRuntime(
        fail_execute=frozenset({"paper::consume"}),
    )
    values = ResearchValueRouter((_ValueAuthority(),))
    graph, pool, research = _bound(tmp_path, runtime, values)
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="retry-preflight")
        target = ResearchExecutionTarget("execution-retry-preflight", revision)
        receipt = research.run(target)
        assert receipt.state == "failed"

        active = graph.active_cut(target.execution_id)
        assert active is not None
        before = graph.node_state(active.cut_id, "paper::consume")
        assert before.state is ResearchGraphLiveNodeState.FAILED

        runtime.fail_execute = frozenset()
        runtime.reject = frozenset({"paper::consume"})
        with pytest.raises(RuntimeError, match="runtime rejected: paper::consume"):
            research.retry(target.for_graph(("paper", "consume")))

        after = graph.node_state(active.cut_id, "paper::consume")
        assert after.state is ResearchGraphLiveNodeState.FAILED
        assert after.attempt_number == before.attempt_number
        assert after.failure_type == before.failure_type
        assert after.failure_message == before.failure_message
    finally:
        pool.close()


def test_retry_and_reconcile_remain_proof_gated(tmp_path: Path) -> None:
    runtime = _Runtime()
    values = ResearchValueRouter((_ValueAuthority(),))
    _graph, pool, research = _bound(tmp_path, runtime, values)
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="proof-gated-control")
        target = ResearchExecutionTarget("execution-proof-gated", revision)
        research.run(target)

        with pytest.raises(
            ResearchExecutionUnsupported,
            match="explicit UnitRef",
        ):
            research.retry(target)
        with pytest.raises(
            ResearchGraphExecutionConflict,
            match="definitively failed",
        ):
            research.retry(target.for_graph(("paper", "source")))
        with pytest.raises(
            ResearchExecutionUnsupported,
            match="no lower-authority reconciliation port",
        ):
            research.reconcile(target)
        with pytest.raises(
            ResearchExecutionUnsupported,
            match="no lower-authority reconciliation port",
        ):
            research.reconcile(target.for_graph(("paper", "source")))
    finally:
        pool.close()



class _ExecutionStoreWithoutActiveCut:
    def ensure_execution_identity(self, execution_id, plan):
        raise AssertionError("unused")

    def materialize_nodes(self, execution_id, plan, node_ids):
        raise AssertionError("unused")

    def snapshot(self, execution_id):
        raise AssertionError("unused")

    def node_state(self, execution_id, node_id):
        raise AssertionError("unused")

    def node_states(self, execution_id, node_ids):
        raise AssertionError("unused")

    def recover_expired(self, execution_id, *, now_ns):
        raise AssertionError("unused")

    def mark_ready(self, execution_id, node_id, *, now_ns):
        raise AssertionError("unused")

    def mark_ready_many(self, execution_id, node_ids, *, now_ns):
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

    def renew_leases(
        self,
        execution_id,
        renewals,
        *,
        now_ns,
        wait_timeout_seconds=None,
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
        failure_provenance,
    ):
        raise AssertionError("unused")

    def retry_failed_subgraph(
        self,
        execution_id,
        failed_node_id,
        *,
        descendant_node_ids,
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

    def mark_blocked_many(self, execution_id, transitions):
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

    def attempt_state(self, execution_id, node_id, attempt_number):
        raise AssertionError("unused")

    def attempts(self, execution_id, node_id):
        raise AssertionError("unused")


def test_control_requires_explicit_active_cut_cas_authority() -> None:
    pool = _pool()
    try:
        with pytest.raises(TypeError, match="active-cut CAS store"):
            StrictResearchControl(
                _ExecutionStoreWithoutActiveCut(),
                pool,
                _Runtime(),
                ResearchValueRouter((_ValueAuthority(),)),
            )
    finally:
        pool.close()



class _ArtifactRuntime(_Runtime):
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
        del lowering, deadline
        task_context.checkpoint()
        self.executed.append(node.graph_node_id)
        if node.graph_node_id == "paper::source":
            return {"stage": "source"}
        if node.graph_node_id == "paper::derive":
            assert inputs["source"] == {"stage": "source"}
            return {"stage": "derived"}
        raise AssertionError(node.graph_node_id)


def _artifact_portfolio() -> NoetriumUnit:
    artifact_type = type_unit(
        "research.artifact",
        GraphStorageKind.ARTIFACT,
    )
    source = structure_unit(
        "source",
        traits=("research.runtime",),
        boundary=boundary_unit(
            outputs=(port_unit("artifact", artifact_type),),
        ),
    )
    derive = structure_unit(
        "derive",
        traits=("research.runtime",),
        boundary=boundary_unit(
            inputs=(port_unit("source", artifact_type),),
            outputs=(port_unit("artifact", artifact_type),),
        ),
    )
    flow = relation_unit(
        (endpoint_unit("source", "artifact"),),
        (endpoint_unit("derive", "source"),),
        "research.flow",
    )
    return structure_unit(
        "paper",
        traits=("research.portfolio",),
        members=(source, derive),
        relations=(flow,),
    )


def test_derived_artifact_requires_and_records_exact_lineage(tmp_path: Path) -> None:
    runtime = _ArtifactRuntime()
    blobs = DirectoryArtifactBlobStore(tmp_path / "artifact-blobs")
    registry = SQLiteArtifactRegistry(tmp_path / "artifact-catalog.sqlite3")
    retention = SQLiteArtifactRetentionStore(tmp_path / "artifact-retention.sqlite3")
    authority = ResearchImmutableValueAuthority(blobs, registry, retention)
    values = ResearchValueRouter((authority,))
    lineage = SQLiteArtifactLineageStore(tmp_path / "artifact-lineage.sqlite3")
    graph, pool, research = _bound(
        tmp_path,
        runtime,
        values,
        artifact_lineage=lineage,
    )
    try:
        portfolio = _artifact_portfolio()
        revision = research.commit(portfolio, message="artifact lineage")
        target = ResearchExecutionTarget("execution-artifact", revision)
        receipt = research.run(target)
        assert receipt.state == "succeeded"

        compilation = compile_research_portfolio_graph(revision, portfolio)
        cut_id = receipt.payload["cut_id"]
        source_node = compilation.binding("paper::source")
        derive_node = compilation.binding("paper::derive")
        source_ref = authority.lookup(
            ResearchValueSubject(
                cut_id,
                source_node.graph_node_id,
                "artifact",
                GraphStorageKind.ARTIFACT,
                source_node.semantic_digest,
            )
        )
        child_ref = authority.lookup(
            ResearchValueSubject(
                cut_id,
                derive_node.graph_node_id,
                "artifact",
                GraphStorageKind.ARTIFACT,
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
    authority = ResearchImmutableValueAuthority(
        DirectoryArtifactBlobStore(tmp_path / "artifact-blobs"),
        SQLiteArtifactRegistry(tmp_path / "artifact-catalog.sqlite3"),
        SQLiteArtifactRetentionStore(tmp_path / "artifact-retention.sqlite3"),
    )
    values = ResearchValueRouter((authority,))
    graph, pool, research = _bound(tmp_path, runtime, values)
    try:
        portfolio = _artifact_portfolio()
        revision = research.commit(portfolio, message="lineage missing")
        target = ResearchExecutionTarget("execution-lineage-missing", revision)
        with pytest.raises(
            ResearchExecutionUnsupported,
            match="ArtifactLineageRelationPort",
        ):
            research.run(target)
        assert graph.active_cut("execution-lineage-missing") is None
    finally:
        pool.close()


def test_run_auto_reconciles_only_newly_fenced_abandoned_owner_generation(
    tmp_path: Path,
) -> None:
    runtime = _ReconciliationRuntime()
    values = ResearchValueRouter((_ValueAuthority(),))
    graph, pool, research = _bound(
        tmp_path,
        runtime,
        values,
        exclusive_owner_generation=True,
    )
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="abandoned-owner-auto-recovery")
        target = ResearchExecutionTarget(
            "execution-auto-abandoned-recovery",
            revision,
        )
        compilation = compile_research_portfolio_graph(revision, portfolio)
        cut = ResearchExecutionCut.from_compilation(target.execution_id, compilation)
        _materialize_execution(graph, cut.cut_id, compilation.execution_unit)
        graph.move_active_cut(target.execution_id, cut.cut_id)
        graph.mark_ready(cut.cut_id, "paper::source", now_ns=1)
        claim = graph.claim(
            cut.cut_id,
            "paper::source",
            owner_id="research-graph-scheduler:dead-generation:worker",
            now_ns=2,
            lease_expires_at_ns=10_000,
        )
        graph.mark_running(
            cut.cut_id,
            "paper::source",
            attempt_id=claim.attempt_id or "",
            owner_id="research-graph-scheduler:dead-generation:worker",
            now_ns=3,
        )

        receipt = research.run(target)

        assert receipt.state == "succeeded"
        assert runtime.executed == ["paper::source", "paper::consume"]
        attempts = graph.attempts(cut.cut_id, "paper::source")
        assert attempts[0].state is ResearchGraphAttemptState.RECONCILED_RETRY
        assert graph.node_control_state(
            cut.cut_id, "paper::source"
        ).phase is ResearchGraphNodeControlPhase.ACTIVE
    finally:
        pool.close()


def test_run_does_not_auto_reconcile_preexisting_manual_recovery_intent(
    tmp_path: Path,
) -> None:
    runtime = _ReconciliationRuntime()
    values = ResearchValueRouter((_ValueAuthority(),))
    graph, pool, research = _bound(
        tmp_path,
        runtime,
        values,
        exclusive_owner_generation=True,
    )
    try:
        portfolio = _portfolio()
        revision = research.commit(portfolio, message="manual-recovery-remains-explicit")
        target = ResearchExecutionTarget(
            "execution-manual-recovery",
            revision,
        )
        compilation = compile_research_portfolio_graph(revision, portfolio)
        cut = ResearchExecutionCut.from_compilation(target.execution_id, compilation)
        _materialize_execution(graph, cut.cut_id, compilation.execution_unit)
        graph.move_active_cut(target.execution_id, cut.cut_id)
        graph.mark_ready(cut.cut_id, "paper::source", now_ns=1)
        claim = graph.claim(
            cut.cut_id,
            "paper::source",
            owner_id="research-graph-scheduler:manual-owner:worker",
            now_ns=2,
            lease_expires_at_ns=(1 << 63) - 1,
        )
        graph.mark_running(
            cut.cut_id,
            "paper::source",
            attempt_id=claim.attempt_id or "",
            owner_id="research-graph-scheduler:manual-owner:worker",
            now_ns=3,
        )
        interrupted = research.interrupt(target.for_graph(("paper", "source")))
        assert interrupted.state == "node_recovery_required"

        receipt = research.run(target)

        assert receipt.state == "node_recovery_required"
        assert runtime.executed == []
        assert graph.node_control_state(
            cut.cut_id, "paper::source"
        ).phase is ResearchGraphNodeControlPhase.RECOVERY_REQUIRED
    finally:
        pool.close()
