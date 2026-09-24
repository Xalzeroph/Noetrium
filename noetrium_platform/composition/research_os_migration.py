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

from .research_os_graph import CompiledResearchOSGraph, CompiledResearchOSGraphNode


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty canonical text")
    return value


@dataclass(frozen=True, slots=True)
class ResearchOSExecutionCut:
    """Immutable physical graph-execution cut behind one logical execution id."""

    execution_id: str
    research_revision_digest: str
    graph_digest: str
    cut_id: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.execution_id, "research execution_id")
        require_sha256(
            self.research_revision_digest,
            "research execution cut revision",
        )
        require_sha256(self.graph_digest, "research execution cut graph_digest")
        object.__setattr__(
            self,
            "cut_id",
            canonical_digest(
                {
                    "execution_id": self.execution_id,
                    "research_revision_digest": self.research_revision_digest,
                    "graph_digest": self.graph_digest,
                }
            ),
        )

    @classmethod
    def from_compilation(
        cls,
        execution_id: str,
        compilation: CompiledResearchOSGraph,
    ) -> "ResearchOSExecutionCut":
        if type(compilation) is not CompiledResearchOSGraph:
            raise TypeError("research execution cut requires compiled Research OS graph")
        return cls(
            execution_id,
            compilation.plan.research_revision_digest,
            compilation.plan.graph_digest,
        )


class ResearchOSNodeMigrationDisposition(StrEnum):
    REUSE_CANDIDATE = "reuse_candidate"
    RESTART = "restart"
    QUIESCE_REQUIRED = "quiesce_required"
    RECONCILE_REQUIRED = "reconcile_required"
    REMOVE = "remove"


@dataclass(frozen=True, slots=True)
class ResearchOSNodeMigration:
    graph_node_id: str
    disposition: ResearchOSNodeMigrationDisposition
    old_semantic_digest: str | None = None
    new_semantic_digest: str | None = None
    source_state: ResearchGraphLiveNodeState | None = None
    source_attempt_number: int = 0

    def __post_init__(self) -> None:
        _text(self.graph_node_id, "research migration graph_node_id")
        if not isinstance(self.disposition, ResearchOSNodeMigrationDisposition):
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
class ResearchOSReuseProof:
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
class ResearchOSReuseMaterializerPort(Protocol):
    """Materialize already-proven immutable outputs into a target execution cut."""

    def materialize_reuse(
        self,
        plan: "ResearchOSExecutionMigrationPlan",
        node: CompiledResearchOSGraphNode,
        proof: ResearchOSReuseProof,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class ResearchOSExecutionActivation:
    cut: ResearchOSExecutionCut
    active_cut: ResearchGraphActiveCutRef
    snapshot: ResearchGraphExecutionSnapshot

    def __post_init__(self) -> None:
        if type(self.cut) is not ResearchOSExecutionCut:
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
class ResearchOSExecutionMigrationMaterialization:
    plan: "ResearchOSExecutionMigrationPlan"
    active_cut: ResearchGraphActiveCutRef
    snapshot: ResearchGraphExecutionSnapshot
    reused_node_ids: tuple[str, ...]
    restart_node_ids: tuple[str, ...]
    preserved_paused_node_ids: tuple[str, ...]
    preserved_cancelled_node_ids: tuple[str, ...]
    control_transfer_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.plan, ResearchOSExecutionMigrationPlan):
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
class ResearchOSExecutionMigrationPlan:
    execution_id: str
    source_cut: ResearchOSExecutionCut
    target_cut: ResearchOSExecutionCut
    nodes: tuple[ResearchOSNodeMigration, ...]
    migration_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.execution_id, "research migration execution_id")
        if type(self.source_cut) is not ResearchOSExecutionCut:
            raise TypeError("research migration source_cut must be typed")
        if type(self.target_cut) is not ResearchOSExecutionCut:
            raise TypeError("research migration target_cut must be typed")
        if (
            self.source_cut.execution_id != self.execution_id
            or self.target_cut.execution_id != self.execution_id
        ):
            raise ValueError("research migration cut logical execution identity drifted")
        if self.source_cut.cut_id == self.target_cut.cut_id:
            raise ValueError("research migration requires different immutable cuts")
        if type(self.nodes) is not tuple or any(
            type(row) is not ResearchOSNodeMigration for row in self.nodes
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
                ResearchOSNodeMigrationDisposition.QUIESCE_REQUIRED,
                ResearchOSNodeMigrationDisposition.RECONCILE_REQUIRED,
            }
            for row in self.nodes
        )

    @property
    def reuse_candidate_node_ids(self) -> tuple[str, ...]:
        return tuple(
            row.graph_node_id
            for row in self.nodes
            if row.disposition is ResearchOSNodeMigrationDisposition.REUSE_CANDIDATE
        )

    @property
    def restart_node_ids(self) -> tuple[str, ...]:
        return tuple(
            row.graph_node_id
            for row in self.nodes
            if row.disposition is ResearchOSNodeMigrationDisposition.RESTART
        )


def plan_research_os_execution_migration(
    execution_id: str,
    source: CompiledResearchOSGraph,
    target: CompiledResearchOSGraph,
    snapshot: ResearchGraphExecutionSnapshot,
) -> ResearchOSExecutionMigrationPlan:
    """Plan a non-destructive revision rebase without rewriting execution history.

    SUCCEEDED nodes with identical semantic digests are only reuse *candidates*.
    Artifact/evidence authorities still have to prove reusable outputs before a
    target cut may materialize them. Active or uncertain source work blocks the
    cut switch until it has been quiesced/reconciled.
    """

    _text(execution_id, "research migration execution_id")
    if type(source) is not CompiledResearchOSGraph:
        raise TypeError("research migration source must be compiled Research OS graph")
    if type(target) is not CompiledResearchOSGraph:
        raise TypeError("research migration target must be compiled Research OS graph")
    if type(snapshot) is not ResearchGraphExecutionSnapshot:
        raise TypeError("research migration snapshot must be ResearchGraphExecutionSnapshot")
    if source.plan.graph_id != target.plan.graph_id:
        raise ValueError("research migration requires the same ResearchPortfolio identity")
    source_cut = ResearchOSExecutionCut.from_compilation(execution_id, source)
    target_cut = ResearchOSExecutionCut.from_compilation(execution_id, target)
    if (
        snapshot.execution_id != source_cut.cut_id
        or snapshot.graph_id != source.plan.graph_id
        or snapshot.graph_digest != source.plan.graph_digest
        or snapshot.research_revision_digest != source.plan.research_revision_digest
    ):
        raise ValueError(
            "research migration source snapshot does not match immutable source cut"
        )

    source_nodes = {node.node_id: node for node in source.plan.nodes}
    target_nodes = {node.node_id: node for node in target.plan.nodes}
    snapshot_nodes = {node.node_id: node for node in snapshot.nodes}
    if set(snapshot_nodes) != set(source_nodes):
        raise ValueError("research migration snapshot/source graph node set drifted")
    for node_id, planned in source_nodes.items():
        observed = snapshot_nodes[node_id]
        if observed.semantic_digest != planned.semantic_digest:
            raise ValueError(
                f"research migration source node semantic identity drifted: {node_id}"
            )

    rows: list[ResearchOSNodeMigration] = []
    for node_id in sorted(set(source_nodes) | set(target_nodes)):
        old = source_nodes.get(node_id)
        new = target_nodes.get(node_id)
        state = None if old is None else snapshot_nodes[node_id].state
        attempt_number = (
            0 if old is None else snapshot_nodes[node_id].attempt_number
        )

        if old is not None and state in {
            ResearchGraphLiveNodeState.CLAIMED,
            ResearchGraphLiveNodeState.RUNNING,
        }:
            disposition = ResearchOSNodeMigrationDisposition.QUIESCE_REQUIRED
        elif old is not None and state is ResearchGraphLiveNodeState.RECONCILE_REQUIRED:
            disposition = ResearchOSNodeMigrationDisposition.RECONCILE_REQUIRED
        elif new is None:
            disposition = ResearchOSNodeMigrationDisposition.REMOVE
        elif old is None:
            disposition = ResearchOSNodeMigrationDisposition.RESTART
        elif (
            old.semantic_digest == new.semantic_digest
            and state is ResearchGraphLiveNodeState.SUCCEEDED
        ):
            disposition = ResearchOSNodeMigrationDisposition.REUSE_CANDIDATE
        else:
            disposition = ResearchOSNodeMigrationDisposition.RESTART

        rows.append(
            ResearchOSNodeMigration(
                node_id,
                disposition,
                None if old is None else old.semantic_digest,
                None if new is None else new.semantic_digest,
                state,
                attempt_number,
            )
        )

    return ResearchOSExecutionMigrationPlan(
        execution_id,
        source_cut,
        target_cut,
        tuple(rows),
    )



def _cut_store(
    execution_store: ResearchGraphExecutionStorePort,
    active_cut_store: ResearchGraphActiveCutStorePort | None,
) -> ResearchGraphActiveCutStorePort:
    selected: object = execution_store if active_cut_store is None else active_cut_store
    if not isinstance(selected, ResearchGraphActiveCutStorePort):
        raise TypeError("research execution migration requires active-cut CAS authority")
    return selected


def activate_research_os_execution_cut(
    execution_id: str,
    compilation: CompiledResearchOSGraph,
    execution_store: ResearchGraphExecutionStorePort,
    *,
    active_cut_store: ResearchGraphActiveCutStorePort | None = None,
) -> ResearchOSExecutionActivation:
    """Create/reopen one immutable physical cut and bind the logical execution ref."""

    _text(execution_id, "research execution activation execution_id")
    if type(compilation) is not CompiledResearchOSGraph:
        raise TypeError("research execution activation requires compiled Research OS graph")
    if not isinstance(execution_store, ResearchGraphExecutionStorePort):
        raise TypeError("research execution activation requires graph execution store")
    cuts = _cut_store(execution_store, active_cut_store)
    cut = ResearchOSExecutionCut.from_compilation(execution_id, compilation)
    active = cuts.active_cut(execution_id)
    if active is not None and active.cut_id != cut.cut_id:
        raise ResearchGraphExecutionConflict(
            "logical Research OS execution is already bound to a different active cut; "
            "revision changes require explicit migration"
        )
    snapshot = execution_store.ensure_execution(cut.cut_id, compilation.plan)
    if active is None:
        active = cuts.move_active_cut(execution_id, cut.cut_id)
    return ResearchOSExecutionActivation(cut, active, snapshot)


def materialize_research_os_execution_migration(
    plan: ResearchOSExecutionMigrationPlan,
    target: CompiledResearchOSGraph,
    execution_store: ResearchGraphExecutionStorePort,
    *,
    reuse_proofs: tuple[ResearchOSReuseProof, ...] = (),
    reuse_materializer: ResearchOSReuseMaterializerPort | None = None,
    active_cut_store: ResearchGraphActiveCutStorePort | None = None,
    now_ns: int,
) -> ResearchOSExecutionMigrationMaterialization:
    """Materialize R2 beside R1, prove safe reuse, then CAS-switch the active cut.

    Every REUSE_CANDIDATE must carry an exact lower-authority proof. Missing,
    extra, stale or mismatched proofs fail closed before the target cut is
    activated. The source cut is never mutated.
    """

    if not isinstance(plan, ResearchOSExecutionMigrationPlan):
        raise TypeError("research migration materialization requires typed plan")
    if type(target) is not CompiledResearchOSGraph:
        raise TypeError("research migration materialization target must be compiled graph")
    if not isinstance(execution_store, ResearchGraphExecutionStorePort):
        raise TypeError("research migration materialization requires graph execution store")
    if type(now_ns) is not int or now_ns < 0:
        raise ValueError("research migration materialization now_ns must be non-negative")
    if not plan.can_switch:
        raise ResearchGraphExecutionConflict(
            "research migration cannot switch while source work needs quiesce/reconcile"
        )
    expected_target = ResearchOSExecutionCut.from_compilation(plan.execution_id, target)
    if expected_target != plan.target_cut:
        raise ValueError("research migration target compilation does not match target cut")
    if type(reuse_proofs) is not tuple or any(
        type(proof) is not ResearchOSReuseProof for proof in reuse_proofs
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

    cuts = _cut_store(execution_store, active_cut_store)
    active = cuts.active_cut(plan.execution_id)
    if active is None or active.cut_id != plan.source_cut.cut_id:
        raise ResearchGraphExecutionConflict(
            "research migration source cut is no longer the active execution cut"
        )
    source_snapshot = execution_store.snapshot(plan.source_cut.cut_id)
    if (
        source_snapshot.graph_digest != plan.source_cut.graph_digest
        or source_snapshot.research_revision_digest
        != plan.source_cut.research_revision_digest
    ):
        raise ResearchGraphExecutionConflict(
            "research migration durable source cut identity drifted"
        )
    if not isinstance(execution_store, ResearchGraphControlStorePort):
        raise TypeError(
            "research migration requires durable graph control authority"
        )
    if not isinstance(execution_store, ResearchGraphNodeControlStorePort):
        raise TypeError(
            "research migration requires durable per-node control authority"
        )
    source_control = execution_store.control_state(plan.source_cut.cut_id)
    if source_control.phase is not ResearchGraphControlPhase.PAUSED:
        raise ResearchGraphExecutionConflict(
            "research migration materialization requires a paused source cut; "
            f"actual={source_control.phase.value}"
        )
    common_node_ids = tuple(
        sorted(
            row.graph_node_id
            for row in plan.nodes
            if row.old_semantic_digest is not None
            and row.new_semantic_digest is not None
        )
    )
    source_node_controls = {
        node_id: execution_store.node_control_state(
            plan.source_cut.cut_id,
            node_id,
        )
        for node_id in common_node_ids
    }
    source_fence = ResearchGraphCutSwitchFence(
        plan.source_cut.cut_id,
        active.generation,
        source_snapshot.generation,
        source_control,
        tuple(source_node_controls[node_id] for node_id in common_node_ids),
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

    target_snapshot = execution_store.ensure_execution(
        plan.target_cut.cut_id,
        target.plan,
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
        target_node = target.node(node_id)
        materialization_digest = None
        if target_node.node.outputs:
            if not isinstance(reuse_materializer, ResearchOSReuseMaterializerPort):
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

    preserved_paused: list[str] = []
    preserved_cancelled: list[str] = []
    for node_id in common_node_ids:
        source_node_control = source_node_controls[node_id]
        target_node_control = execution_store.node_control_state(
            plan.target_cut.cut_id,
            node_id,
        )
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

    for node_id, observed in source_node_controls.items():
        current = execution_store.node_control_state(
            plan.source_cut.cut_id,
            node_id,
        )
        if current != observed:
            raise ResearchGraphExecutionConflict(
                "research migration source node control changed during materialization: "
                f"{node_id}"
            )

    target_snapshot = execution_store.snapshot(plan.target_cut.cut_id)
    expected_restart = set(plan.restart_node_ids) - set(preserved_cancelled)
    actual_restart = {
        node.node_id
        for node in target_snapshot.nodes
        if node.state is ResearchGraphLiveNodeState.PENDING
    }
    if actual_restart != expected_restart:
        raise ResearchGraphExecutionConflict(
            "research migration target cut restart set drifted: "
            f"expected={tuple(sorted(expected_restart))}, "
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
    target_node_controls = {
        node_id: execution_store.node_control_state(
            plan.target_cut.cut_id,
            node_id,
        )
        for node_id in common_node_ids
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
                for node_id in common_node_ids
            ),
            "target": tuple(
                (
                    node_id,
                    target_node_controls[node_id].phase.value,
                    target_node_controls[node_id].generation,
                )
                for node_id in common_node_ids
            ),
        }
    )
    active = cuts.move_active_cut(
        plan.execution_id,
        plan.target_cut.cut_id,
        expected_cut_id=plan.source_cut.cut_id,
        source_fence=source_fence,
    )
    return ResearchOSExecutionMigrationMaterialization(
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
    "ResearchOSExecutionActivation",
    "ResearchOSExecutionCut",
    "ResearchOSExecutionMigrationMaterialization",
    "ResearchOSExecutionMigrationPlan",
    "ResearchOSNodeMigration",
    "ResearchOSNodeMigrationDisposition",
    "ResearchOSReuseMaterializerPort",
    "ResearchOSReuseProof",
    "activate_research_os_execution_cut",
    "materialize_research_os_execution_migration",
    "plan_research_os_execution_migration",
]
