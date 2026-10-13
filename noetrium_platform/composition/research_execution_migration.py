from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphActiveCutRef,
    ResearchGraphActiveCutStorePort,
    ResearchGraphControlPhase,
    ResearchGraphControlStorePort,
    ResearchGraphCutSwitchFence,
    ResearchGraphExecutionConflict,
    ResearchGraphExecutionSnapshot,
    ResearchGraphExecutionStorePort,
    ResearchGraphLiveNodeState,
    ResearchGraphNodeControlPhase,
    ResearchGraphNodeControlStorePort,
)

from .research_execution_graph import ResearchCompilationView, ResearchExecutionBinding


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty canonical text")
    return value


@dataclass(frozen=True, slots=True)
class ResearchExecutionCut:
    """Immutable physical graph-execution cut behind one logical execution id."""

    execution_id: str
    research_revision_digest: str
    graph_digest: str
    generation: int = 1
    cut_id: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.execution_id, "research execution_id")
        require_sha256(
            self.research_revision_digest,
            "research execution cut revision",
        )
        require_sha256(self.graph_digest, "research execution cut graph_digest")
        if type(self.generation) is not int or self.generation < 1:
            raise ValueError("research execution cut generation must be positive")
        object.__setattr__(
            self,
            "cut_id",
            canonical_digest(
                {
                    "execution_id": self.execution_id,
                    "research_revision_digest": self.research_revision_digest,
                    "graph_digest": self.graph_digest,
                    "generation": self.generation,
                }
            ),
        )

    @classmethod
    def from_compilation(
        cls,
        execution_id: str,
        compilation: ResearchCompilationView,
        *,
        generation: int = 1,
    ) -> "ResearchExecutionCut":
        if type(compilation) is not ResearchCompilationView:
            raise TypeError("research execution cut requires compiled Research execution graph")
        return cls(
            execution_id,
            compilation.research_revision_digest,
            compilation.graph_digest,
            generation,
        )


class ResearchNodeMigrationDisposition(StrEnum):
    REUSE_CANDIDATE = "reuse_candidate"
    RESTART = "restart"
    QUIESCE_REQUIRED = "quiesce_required"
    RECONCILE_REQUIRED = "reconcile_required"
    REMOVE = "remove"


@dataclass(frozen=True, slots=True)
class ResearchNodeMigration:
    graph_node_id: str
    disposition: ResearchNodeMigrationDisposition
    old_semantic_digest: str | None = None
    new_semantic_digest: str | None = None
    source_state: ResearchGraphLiveNodeState | None = None
    source_attempt_number: int = 0

    def __post_init__(self) -> None:
        _text(self.graph_node_id, "research migration graph_node_id")
        if not isinstance(self.disposition, ResearchNodeMigrationDisposition):
            raise TypeError("research migration disposition must be typed")
        for field_name, value in (
            ("old_semantic_digest", self.old_semantic_digest),
            ("new_semantic_digest", self.new_semantic_digest),
        ):
            if value is not None:
                require_sha256(value, f"research migration {field_name}")
        if self.source_state is not None and not isinstance(
            self.source_state,
            ResearchGraphLiveNodeState,
        ):
            raise TypeError("research migration source_state must be typed")
        if type(self.source_attempt_number) is not int or self.source_attempt_number < 0:
            raise ValueError("research migration source_attempt_number must be non-negative")


@dataclass(frozen=True, slots=True)
class ResearchReuseProof:
    """Lower-authority proof that one completed semantic node can be reused."""

    graph_node_id: str
    source_cut_id: str
    semantic_digest: str
    proof_digest: str

    def __post_init__(self) -> None:
        _text(self.graph_node_id, "research reuse proof graph_node_id")
        require_sha256(self.source_cut_id, "research reuse proof source_cut_id")
        require_sha256(self.semantic_digest, "research reuse proof semantic_digest")
        require_sha256(self.proof_digest, "research reuse proof proof_digest")


@runtime_checkable
class ResearchReuseMaterializerPort(Protocol):
    """Materialize already-proven immutable outputs into a target execution cut."""

    def materialize_reuse(
        self,
        plan: "ResearchExecutionMigrationDecision",
        node: ResearchExecutionBinding,
        proof: ResearchReuseProof,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class ResearchExecutionActivation:
    cut: ResearchExecutionCut
    active_cut: ResearchGraphActiveCutRef
    snapshot: ResearchGraphExecutionSnapshot

    def __post_init__(self) -> None:
        if type(self.cut) is not ResearchExecutionCut:
            raise TypeError("research execution activation cut must be typed")
        if type(self.active_cut) is not ResearchGraphActiveCutRef:
            raise TypeError("research execution activation active_cut must be typed")
        if type(self.snapshot) is not ResearchGraphExecutionSnapshot:
            raise TypeError("research execution activation snapshot must be typed")
        if self.active_cut.cut_id != self.cut.cut_id:
            raise ValueError("research execution activation cut identity drifted")
        if self.snapshot.execution_id != self.cut.cut_id:
            raise ValueError("research execution activation snapshot cut drifted")


@dataclass(frozen=True, slots=True)
class ResearchExecutionMigrationMaterialization:
    plan: "ResearchExecutionMigrationDecision"
    active_cut: ResearchGraphActiveCutRef
    snapshot: ResearchGraphExecutionSnapshot
    reused_node_ids: tuple[str, ...]
    restart_node_ids: tuple[str, ...]
    preserved_paused_node_ids: tuple[str, ...]
    preserved_cancelled_node_ids: tuple[str, ...]
    control_transfer_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.plan, ResearchExecutionMigrationDecision):
            raise TypeError("research migration materialization plan must be typed")
        if type(self.active_cut) is not ResearchGraphActiveCutRef:
            raise TypeError("research migration materialization active_cut must be typed")
        if type(self.snapshot) is not ResearchGraphExecutionSnapshot:
            raise TypeError("research migration materialization snapshot must be typed")
        reused = tuple(sorted(self.reused_node_ids))
        restart = tuple(sorted(self.restart_node_ids))
        paused = tuple(sorted(self.preserved_paused_node_ids))
        cancelled = tuple(sorted(self.preserved_cancelled_node_ids))
        groups = (reused, restart, paused, cancelled)
        if any(len(group) != len(set(group)) for group in groups):
            raise ValueError(
                "research migration materialization node ids must be unique"
            )
        if set(reused) & set(restart):
            raise ValueError(
                "research migration reused/restart node sets must be disjoint"
            )
        if set(cancelled) & (set(reused) | set(restart) | set(paused)):
            raise ValueError(
                "research migration cancelled nodes cannot also be reused/restarted/paused"
            )
        require_sha256(
            self.control_transfer_digest,
            "research migration control_transfer_digest",
        )
        if self.active_cut.cut_id != self.plan.target_cut.cut_id:
            raise ValueError("research migration active cut does not match target cut")
        if self.snapshot.execution_id != self.plan.target_cut.cut_id:
            raise ValueError("research migration snapshot does not match target cut")
        object.__setattr__(self, "reused_node_ids", reused)
        object.__setattr__(self, "restart_node_ids", restart)
        object.__setattr__(self, "preserved_paused_node_ids", paused)
        object.__setattr__(self, "preserved_cancelled_node_ids", cancelled)


@dataclass(frozen=True, slots=True)
class ResearchExecutionMigrationDecision:
    execution_id: str
    source_cut: ResearchExecutionCut
    target_cut: ResearchExecutionCut
    nodes: tuple[ResearchNodeMigration, ...]
    migration_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.execution_id, "research migration execution_id")
        if type(self.source_cut) is not ResearchExecutionCut:
            raise TypeError("research migration source_cut must be typed")
        if type(self.target_cut) is not ResearchExecutionCut:
            raise TypeError("research migration target_cut must be typed")
        if (
            self.source_cut.execution_id != self.execution_id
            or self.target_cut.execution_id != self.execution_id
        ):
            raise ValueError("research migration cut logical execution identity drifted")
        if self.source_cut.cut_id == self.target_cut.cut_id:
            raise ValueError("research migration requires different immutable cuts")
        if type(self.nodes) is not tuple or any(
            type(row) is not ResearchNodeMigration for row in self.nodes
        ):
            raise TypeError("research migration nodes must be typed tuple")
        ordered = tuple(sorted(self.nodes, key=lambda row: row.graph_node_id))
        ids = tuple(row.graph_node_id for row in ordered)
        if len(ids) != len(set(ids)):
            raise ValueError("research migration node ids must be unique")
        object.__setattr__(self, "nodes", ordered)
        object.__setattr__(
            self,
            "migration_digest",
            canonical_digest(
                {
                    "execution_id": self.execution_id,
                    "source_cut": self.source_cut.cut_id,
                    "target_cut": self.target_cut.cut_id,
                    "nodes": tuple(
                        (
                            row.graph_node_id,
                            row.disposition.value,
                            row.old_semantic_digest,
                            row.new_semantic_digest,
                            None if row.source_state is None else row.source_state.value,
                            row.source_attempt_number,
                        )
                        for row in ordered
                    ),
                }
            ),
        )

    @property
    def can_switch(self) -> bool:
        return not any(
            row.disposition
            in {
                ResearchNodeMigrationDisposition.QUIESCE_REQUIRED,
                ResearchNodeMigrationDisposition.RECONCILE_REQUIRED,
            }
            for row in self.nodes
        )

    @property
    def reuse_candidate_node_ids(self) -> tuple[str, ...]:
        return tuple(
            row.graph_node_id
            for row in self.nodes
            if row.disposition is ResearchNodeMigrationDisposition.REUSE_CANDIDATE
        )

    @property
    def restart_node_ids(self) -> tuple[str, ...]:
        return tuple(
            row.graph_node_id
            for row in self.nodes
            if row.disposition is ResearchNodeMigrationDisposition.RESTART
        )


def plan_research_execution_migration(
    execution_id: str,
    source: ResearchCompilationView,
    target: ResearchCompilationView,
    snapshot: ResearchGraphExecutionSnapshot,
    *,
    source_generation: int = 1,
    target_generation: int = 2,
) -> ResearchExecutionMigrationDecision:
    """Plan a non-destructive revision rebase without rewriting execution history.

    SUCCEEDED nodes with identical semantic digests are only reuse *candidates*.
    Artifact/evidence authorities still have to prove reusable outputs before a
    target cut may materialize them. Active or uncertain source work blocks the
    cut switch until it has been quiesced/reconciled.
    """

    _text(execution_id, "research migration execution_id")
    if type(source) is not ResearchCompilationView:
        raise TypeError("research migration source must be compiled Research execution graph")
    if type(target) is not ResearchCompilationView:
        raise TypeError("research migration target must be compiled Research execution graph")
    if type(snapshot) is not ResearchGraphExecutionSnapshot:
        raise TypeError("research migration snapshot must be ResearchGraphExecutionSnapshot")
    if source.graph_id != target.graph_id:
        raise ValueError("research migration requires the same NoetriumUnit root identity")
    source_cut = ResearchExecutionCut.from_compilation(
        execution_id, source, generation=source_generation
    )
    target_cut = ResearchExecutionCut.from_compilation(
        execution_id, target, generation=target_generation
    )
    if (
        snapshot.execution_id != source_cut.cut_id
        or snapshot.graph_id != source.graph_id
        or snapshot.graph_digest != source.graph_digest
        or snapshot.research_revision_digest != source.research_revision_digest
    ):
        raise ValueError(
            "research migration source snapshot does not match immutable source cut"
        )

    snapshot_nodes = {node.node_id: node for node in snapshot.nodes}

    source_binding_cache: dict[str, ResearchExecutionBinding | None] = {}
    target_binding_cache: dict[str, ResearchExecutionBinding | None] = {}

    def binding_or_none(
        compilation: ResearchCompilationView,
        node_id: str,
        cache: dict[str, ResearchExecutionBinding | None],
    ) -> ResearchExecutionBinding | None:
        if node_id in cache:
            return cache[node_id]
        try:
            value = compilation.binding(node_id)
        except KeyError:
            value = None
        cache[node_id] = value
        return value

    for node_id, observed in snapshot_nodes.items():
        planned = binding_or_none(source, node_id, source_binding_cache)
        if planned is None:
            raise ValueError(
                "research migration snapshot references node outside source graph: "
                f"{node_id}"
            )
        if observed.semantic_digest != planned.semantic_digest:
            raise ValueError(
                f"research migration source node semantic identity drifted: {node_id}"
            )

    stable_cache: dict[str, bool] = {}
    evaluating: set[str] = set()

    def statically_reusable(node_id: str) -> bool:
        cached = stable_cache.get(node_id)
        if cached is not None:
            return cached
        if node_id in evaluating:
            raise ValueError(
                "research migration dependency cycle escaped graph compilation: "
                f"{node_id}"
            )
        evaluating.add(node_id)
        try:
            old = binding_or_none(source, node_id, source_binding_cache)
            new = binding_or_none(target, node_id, target_binding_cache)
            reusable = (
                old is not None
                and new is not None
                and old.semantic_digest == new.semantic_digest
                and old.incoming_dependency_digests
                == new.incoming_dependency_digests
                and old.depends_on_node_ids == new.depends_on_node_ids
            )
            if reusable:
                reusable = all(
                    statically_reusable(dependency)
                    for dependency in new.depends_on_node_ids
                )
            stable_cache[node_id] = reusable
            return reusable
        finally:
            evaluating.remove(node_id)

    rows: list[ResearchNodeMigration] = []
    for node_id in sorted(snapshot_nodes):
        observed = snapshot_nodes[node_id]
        old = binding_or_none(source, node_id, source_binding_cache)
        if old is None:
            raise AssertionError("validated source node disappeared during migration")
        new = binding_or_none(target, node_id, target_binding_cache)
        state = observed.state
        attempt_number = observed.attempt_number

        if state in {
            ResearchGraphLiveNodeState.CLAIMED,
            ResearchGraphLiveNodeState.RUNNING,
        }:
            disposition = ResearchNodeMigrationDisposition.QUIESCE_REQUIRED
        elif state is ResearchGraphLiveNodeState.RECONCILE_REQUIRED:
            disposition = ResearchNodeMigrationDisposition.RECONCILE_REQUIRED
        elif new is None:
            disposition = ResearchNodeMigrationDisposition.REMOVE
        elif (
            state is ResearchGraphLiveNodeState.SUCCEEDED
            and statically_reusable(node_id)
        ):
            disposition = ResearchNodeMigrationDisposition.REUSE_CANDIDATE
        else:
            disposition = ResearchNodeMigrationDisposition.RESTART

        rows.append(
            ResearchNodeMigration(
                node_id,
                disposition,
                old.semantic_digest,
                None if new is None else new.semantic_digest,
                state,
                attempt_number,
            )
        )

    return ResearchExecutionMigrationDecision(
        execution_id,
        source_cut,
        target_cut,
        tuple(rows),
    )



def activate_research_execution_cut(
    execution_id: str,
    compilation: ResearchCompilationView,
    execution_store: ResearchGraphExecutionStorePort,
    *,
    generation: int = 1,
) -> ResearchExecutionActivation:
    """Create/reopen one immutable physical cut and bind the logical execution ref."""

    _text(execution_id, "research execution activation execution_id")
    if type(compilation) is not ResearchCompilationView:
        raise TypeError("research execution activation requires compiled Research execution graph")
    if not isinstance(execution_store, ResearchGraphExecutionStorePort):
        raise TypeError("research execution activation requires graph execution store")
    if not isinstance(execution_store, ResearchGraphActiveCutStorePort):
        raise TypeError(
            "research execution activation requires unified active-cut Graph authority"
        )
    cut = ResearchExecutionCut.from_compilation(
        execution_id, compilation, generation=generation
    )
    observed = execution_store.active_execution_snapshot(execution_id)
    active = None if observed is None else observed.active_cut
    if active is not None and active.cut_id != cut.cut_id:
        raise ResearchGraphExecutionConflict(
            "logical Research execution execution is already bound to a different active cut; "
            "revision changes require explicit migration"
        )
    snapshot = execution_store.ensure_execution_identity(
        cut.cut_id,
        compilation.execution_unit,
    )
    if active is None:
        active = execution_store.move_active_cut(execution_id, cut.cut_id)
    return ResearchExecutionActivation(cut, active, snapshot)


def materialize_research_execution_migration(
    plan: ResearchExecutionMigrationDecision,
    target: ResearchCompilationView,
    execution_store: ResearchGraphExecutionStorePort,
    *,
    reuse_proofs: tuple[ResearchReuseProof, ...] = (),
    reuse_materializer: ResearchReuseMaterializerPort | None = None,
    now_ns: int,
) -> ResearchExecutionMigrationMaterialization:
    """Materialize R2 beside R1, prove safe reuse, then CAS-switch the active cut.

    Every REUSE_CANDIDATE must carry an exact lower-authority proof. Missing,
    extra, stale or mismatched proofs fail closed before the target cut is
    activated. The source cut is never mutated.
    """

    if not isinstance(plan, ResearchExecutionMigrationDecision):
        raise TypeError("research migration materialization requires typed plan")
    if type(target) is not ResearchCompilationView:
        raise TypeError("research migration materialization target must be compiled graph")
    if not isinstance(execution_store, ResearchGraphExecutionStorePort):
        raise TypeError("research migration materialization requires graph execution store")
    if type(now_ns) is not int or now_ns < 0:
        raise ValueError("research migration materialization now_ns must be non-negative")
    if not plan.can_switch:
        raise ResearchGraphExecutionConflict(
            "research migration cannot switch while source work needs quiesce/reconcile"
        )
    expected_target = ResearchExecutionCut.from_compilation(
        plan.execution_id,
        target,
        generation=plan.target_cut.generation,
    )
    if expected_target != plan.target_cut:
        raise ValueError("research migration target compilation does not match target cut")
    if type(reuse_proofs) is not tuple or any(
        type(proof) is not ResearchReuseProof for proof in reuse_proofs
    ):
        raise TypeError("research migration reuse_proofs must be typed tuple")
    proofs = {proof.graph_node_id: proof for proof in reuse_proofs}
    if len(proofs) != len(reuse_proofs):
        raise ValueError("research migration reuse proofs must have unique node ids")

    by_id = {row.graph_node_id: row for row in plan.nodes}
    candidates = set(plan.reuse_candidate_node_ids)
    provided = set(proofs)
    unknown = tuple(sorted(provided - candidates))
    if unknown:
        raise ValueError(
            f"research migration proof supplied for non-reuse candidates: {unknown}"
        )
    missing = tuple(sorted(candidates - provided))
    if missing:
        raise ResearchGraphExecutionConflict(
            "research migration is missing mandatory reuse proofs: "
            f"{missing}"
        )
    for node_id, proof in proofs.items():
        row = by_id[node_id]
        if (
            proof.source_cut_id != plan.source_cut.cut_id
            or proof.semantic_digest != row.old_semantic_digest
            or proof.semantic_digest != row.new_semantic_digest
        ):
            raise ValueError(
                f"research migration reuse proof identity drifted: {node_id}"
            )

    if not isinstance(execution_store, ResearchGraphActiveCutStorePort):
        raise TypeError(
            "research migration requires unified active-cut Graph authority"
        )
    if not isinstance(execution_store, ResearchGraphControlStorePort):
        raise TypeError(
            "research migration requires durable graph control authority"
        )
    if not isinstance(execution_store, ResearchGraphNodeControlStorePort):
        raise TypeError(
            "research migration requires durable per-node control authority"
        )
    observed = execution_store.active_execution_snapshot(plan.execution_id)
    if (
        observed is None
        or observed.active_cut.cut_id != plan.source_cut.cut_id
    ):
        raise ResearchGraphExecutionConflict(
            "research migration source cut is no longer the active execution cut"
        )
    active = observed.active_cut
    source_snapshot = observed.execution
    source_control = observed.control
    if (
        source_snapshot.graph_digest != plan.source_cut.graph_digest
        or source_snapshot.research_revision_digest
        != plan.source_cut.research_revision_digest
    ):
        raise ResearchGraphExecutionConflict(
            "research migration durable source cut identity drifted"
        )
    if source_control.phase is not ResearchGraphControlPhase.PAUSED:
        raise ResearchGraphExecutionConflict(
            "research migration materialization requires a paused source cut; "
            f"actual={source_control.phase.value}"
        )
    source_materialized_ids = {
        node.node_id for node in source_snapshot.nodes
    }
    materialized_common_node_ids = tuple(
        sorted(
            row.graph_node_id
            for row in plan.nodes
            if row.graph_node_id in source_materialized_ids
            and row.old_semantic_digest is not None
            and row.new_semantic_digest is not None
        )
    )
    source_control_snapshot = {
        row.node_id: row
        for row in execution_store.node_control_snapshot(plan.source_cut.cut_id)
    }
    missing_source_controls = tuple(
        sorted(
            set(materialized_common_node_ids)
            - set(source_control_snapshot)
        )
    )
    if missing_source_controls:
        raise ResearchGraphExecutionConflict(
            "research migration source node control snapshot is incomplete: "
            f"{missing_source_controls}"
        )
    source_node_controls = {
        node_id: source_control_snapshot[node_id]
        for node_id in materialized_common_node_ids
    }
    source_fence = ResearchGraphCutSwitchFence(
        plan.source_cut.cut_id,
        active.generation,
        source_snapshot.generation,
        source_control,
        tuple(
            source_node_controls[node_id]
            for node_id in materialized_common_node_ids
        ),
    )
    unsettled = tuple(
        sorted(
            (node_id, control.phase.value)
            for node_id, control in source_node_controls.items()
            if control.phase in {
                ResearchGraphNodeControlPhase.DRAINING,
                ResearchGraphNodeControlPhase.RECOVERY_REQUIRED,
            }
        )
    )
    if unsettled:
        raise ResearchGraphExecutionConflict(
            "research migration source node control must settle before migration: "
            f"{unsettled}"
        )
    for node_id, control in source_node_controls.items():
        source_record = source_snapshot.node(node_id)
        if (
            source_record.state is ResearchGraphLiveNodeState.CANCELLED
        ) != (
            control.phase is ResearchGraphNodeControlPhase.CANCELLED
        ):
            raise ResearchGraphExecutionConflict(
                "research migration source node cancellation truth drifted: "
                f"{node_id}"
            )

    target_snapshot = execution_store.ensure_execution_identity(
        plan.target_cut.cut_id,
        target.execution_unit,
    )
    target_materialize_ids = tuple(
        row.graph_node_id
        for row in plan.nodes
        if row.new_semantic_digest is not None
    )
    if target_materialize_ids:
        execution_store.materialize_nodes(
            plan.target_cut.cut_id,
            target.execution_unit,
            target_materialize_ids,
        )
        target_snapshot = execution_store.snapshot(
            plan.target_cut.cut_id
        )
    target_control = execution_store.control_state(plan.target_cut.cut_id)
    if target_control.phase is ResearchGraphControlPhase.ACTIVE:
        target_control = execution_store.request_drain(
            plan.target_cut.cut_id,
            expected_generation=target_control.generation,
            now_ns=now_ns,
        )
        target_control = execution_store.pause_if_quiescent(
            plan.target_cut.cut_id,
            expected_generation=target_control.generation,
            now_ns=now_ns,
        )
    if target_control.phase is not ResearchGraphControlPhase.PAUSED:
        raise ResearchGraphExecutionConflict(
            "research migration target cut must be paused before active-cut CAS; "
            f"actual={target_control.phase.value}"
        )
    reused: list[str] = []
    for node_id in sorted(proofs):
        proof = proofs[node_id]
        row = by_id[node_id]
        if row.new_semantic_digest is None:
            raise RuntimeError("reuse candidate unexpectedly has no target semantic digest")
        target_node = target.binding(node_id)
        materialization_digest = None
        if target_node.graph.boundary.outputs:
            if not isinstance(reuse_materializer, ResearchReuseMaterializerPort):
                raise ResearchGraphExecutionConflict(
                    "research migration reuse with declared outputs requires an "
                    "explicit lower-authority value materializer"
                )
            materialization_digest = require_sha256(
                reuse_materializer.materialize_reuse(
                    plan,
                    target_node,
                    proof,
                ),
                "research migration reuse materialization proof",
            )
        combined_proof_digest = canonical_digest(
            {
                "source_reuse_proof": proof.proof_digest,
                "target_materialization_proof": materialization_digest,
            }
        )
        execution_store.mark_reused(
            plan.target_cut.cut_id,
            node_id,
            source_execution_id=plan.source_cut.cut_id,
            source_node_id=node_id,
            semantic_digest=row.new_semantic_digest,
            proof_digest=combined_proof_digest,
            now_ns=now_ns,
        )
        reused.append(node_id)

    target_control_snapshot = {
        row.node_id: row
        for row in execution_store.node_control_snapshot(plan.target_cut.cut_id)
    }
    missing_target_controls = tuple(
        sorted(
            set(materialized_common_node_ids)
            - set(target_control_snapshot)
        )
    )
    if missing_target_controls:
        raise ResearchGraphExecutionConflict(
            "research migration target node control snapshot is incomplete: "
            f"{missing_target_controls}"
        )
    preserved_paused: list[str] = []
    preserved_cancelled: list[str] = []
    for node_id in materialized_common_node_ids:
        source_node_control = source_node_controls[node_id]
        target_node_control = target_control_snapshot[node_id]
        if source_node_control.phase is ResearchGraphNodeControlPhase.ACTIVE:
            if target_node_control.phase is ResearchGraphNodeControlPhase.DRAINING:
                target_node_control = execution_store.pause_node_if_quiescent(
                    plan.target_cut.cut_id,
                    node_id,
                    expected_generation=target_node_control.generation,
                    now_ns=now_ns,
                )
            if target_node_control.phase is ResearchGraphNodeControlPhase.PAUSED:
                target_node_control = execution_store.resume_node(
                    plan.target_cut.cut_id,
                    node_id,
                    expected_generation=target_node_control.generation,
                    now_ns=now_ns,
                )
            if target_node_control.phase is not ResearchGraphNodeControlPhase.ACTIVE:
                raise ResearchGraphExecutionConflict(
                    "research migration target staging carries stale node control "
                    f"intent: {node_id}={target_node_control.phase.value}"
                )
        elif source_node_control.phase is ResearchGraphNodeControlPhase.PAUSED:
            if target_node_control.phase is ResearchGraphNodeControlPhase.ACTIVE:
                target_node_control = execution_store.request_node_drain(
                    plan.target_cut.cut_id,
                    node_id,
                    expected_generation=target_node_control.generation,
                    now_ns=now_ns,
                )
            if target_node_control.phase is ResearchGraphNodeControlPhase.DRAINING:
                target_node_control = execution_store.pause_node_if_quiescent(
                    plan.target_cut.cut_id,
                    node_id,
                    expected_generation=target_node_control.generation,
                    now_ns=now_ns,
                )
            if target_node_control.phase is not ResearchGraphNodeControlPhase.PAUSED:
                raise ResearchGraphExecutionConflict(
                    "research migration failed to preserve paused node control: "
                    f"{node_id}"
                )
            preserved_paused.append(node_id)
        elif source_node_control.phase is ResearchGraphNodeControlPhase.CANCELLED:
            if target_node_control.phase is ResearchGraphNodeControlPhase.ACTIVE:
                target_node_control = execution_store.cancel_node_subgraph(
                    plan.target_cut.cut_id,
                    node_id,
                    descendant_node_ids=(),
                    expected_generation=target_node_control.generation,
                    now_ns=now_ns,
                )
            if target_node_control.phase is not ResearchGraphNodeControlPhase.CANCELLED:
                raise ResearchGraphExecutionConflict(
                    "research migration failed to preserve cancelled node control: "
                    f"{node_id}"
                )
            if (
                execution_store.node_state(
                    plan.target_cut.cut_id,
                    node_id,
                ).state
                is not ResearchGraphLiveNodeState.CANCELLED
            ):
                raise ResearchGraphExecutionConflict(
                    "research migration cancelled node control disagrees with "
                    f"target execution state: {node_id}"
                )
            preserved_cancelled.append(node_id)
        else:
            raise ResearchGraphExecutionConflict(
                "research migration encountered unsupported source node control phase: "
                f"{node_id}={source_node_control.phase.value}"
            )

    current_source_controls = {
        row.node_id: row
        for row in execution_store.node_control_snapshot(plan.source_cut.cut_id)
    }
    for node_id, observed in source_node_controls.items():
        current = current_source_controls.get(node_id)
        if current != observed:
            raise ResearchGraphExecutionConflict(
                "research migration source node control changed during materialization: "
                f"{node_id}"
            )

    target_snapshot = execution_store.snapshot(plan.target_cut.cut_id)
    expected_restart = set(plan.restart_node_ids) - set(preserved_cancelled)
    expected_materialized_restart = (
        expected_restart & set(target_materialize_ids)
    )
    actual_restart = {
        node.node_id
        for node in target_snapshot.nodes
        if node.state is ResearchGraphLiveNodeState.PENDING
    }
    if actual_restart != expected_materialized_restart:
        raise ResearchGraphExecutionConflict(
            "research migration target cut materialized restart set drifted: "
            f"expected={tuple(sorted(expected_materialized_restart))}, "
            f"actual={tuple(sorted(actual_restart))}"
        )
    unexpected_states = tuple(
        sorted(
            (node.node_id, node.state.value)
            for node in target_snapshot.nodes
            if node.state
            not in {
                ResearchGraphLiveNodeState.PENDING,
                ResearchGraphLiveNodeState.REUSED,
                ResearchGraphLiveNodeState.CANCELLED,
            }
        )
    )
    if unexpected_states:
        raise ResearchGraphExecutionConflict(
            "research migration target cut contains unexpected node states: "
            f"{unexpected_states}"
        )
    current_target_controls = {
        row.node_id: row
        for row in execution_store.node_control_snapshot(plan.target_cut.cut_id)
    }
    missing_current_target_controls = tuple(
        sorted(
            set(materialized_common_node_ids)
            - set(current_target_controls)
        )
    )
    if missing_current_target_controls:
        raise ResearchGraphExecutionConflict(
            "research migration target control proof snapshot is incomplete: "
            f"{missing_current_target_controls}"
        )
    target_node_controls = {
        node_id: current_target_controls[node_id]
        for node_id in materialized_common_node_ids
    }
    control_transfer_digest = canonical_digest(
        {
            "source_cut_id": plan.source_cut.cut_id,
            "target_cut_id": plan.target_cut.cut_id,
            "source_fence_digest": source_fence.fence_digest,
            "source": tuple(
                (
                    node_id,
                    source_node_controls[node_id].phase.value,
                    source_node_controls[node_id].generation,
                )
                for node_id in materialized_common_node_ids
            ),
            "target": tuple(
                (
                    node_id,
                    target_node_controls[node_id].phase.value,
                    target_node_controls[node_id].generation,
                )
                for node_id in materialized_common_node_ids
            ),
        }
    )
    active = execution_store.move_active_cut(
        plan.execution_id,
        plan.target_cut.cut_id,
        expected_cut_id=plan.source_cut.cut_id,
        source_fence=source_fence,
    )
    return ResearchExecutionMigrationMaterialization(
        plan,
        active,
        target_snapshot,
        tuple(reused),
        tuple(sorted(expected_restart)),
        tuple(preserved_paused),
        tuple(preserved_cancelled),
        control_transfer_digest,
    )


__all__ = [
    "ResearchExecutionActivation",
    "ResearchExecutionCut",
    "ResearchExecutionMigrationMaterialization",
    "ResearchExecutionMigrationDecision",
    "ResearchNodeMigration",
    "ResearchNodeMigrationDisposition",
    "ResearchReuseMaterializerPort",
    "ResearchReuseProof",
    "activate_research_execution_cut",
    "materialize_research_execution_migration",
    "plan_research_execution_migration",
]
