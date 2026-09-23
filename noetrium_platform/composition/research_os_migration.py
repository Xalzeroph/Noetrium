from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphExecutionSnapshot,
    ResearchGraphLiveNodeState,
)

from .research_os_graph import CompiledResearchOSGraph


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
    if (
        snapshot.graph_id != source.plan.graph_id
        or snapshot.graph_digest != source.plan.graph_digest
        or snapshot.research_revision_digest != source.plan.research_revision_digest
    ):
        raise ValueError("research migration source snapshot does not match source cut")

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
        ResearchOSExecutionCut.from_compilation(execution_id, source),
        ResearchOSExecutionCut.from_compilation(execution_id, target),
        tuple(rows),
    )


__all__ = [
    "ResearchOSExecutionCut",
    "ResearchOSExecutionMigrationPlan",
    "ResearchOSNodeMigration",
    "ResearchOSNodeMigrationDisposition",
    "plan_research_os_execution_migration",
]
