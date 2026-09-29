from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    MachineCut,
    canonical_digest,
    freeze_json,
    require_sha256,
)


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field_name} must be canonical non-empty text")
    return value


@dataclass(frozen=True, slots=True)
class ResearchOSNodeCheckpointProof:
    """Exact lower-Machine proof for one successfully executed ResearchGraph node."""

    execution_cut_id: str
    graph_node_id: str
    semantic_digest: str
    lowering_digest: str
    authority_id: str
    machine_cut: MachineCut
    evidence_digests: tuple[str, ...]
    proof_digest: str = field(init=False)

    def __post_init__(self) -> None:
        require_sha256(self.execution_cut_id, "checkpoint execution_cut_id")
        _text(self.graph_node_id, "checkpoint graph_node_id")
        require_sha256(self.semantic_digest, "checkpoint semantic_digest")
        require_sha256(self.lowering_digest, "checkpoint lowering_digest")
        _text(self.authority_id, "checkpoint authority_id")
        if not isinstance(self.machine_cut, MachineCut):
            raise TypeError("checkpoint proof requires MachineCut")
        if type(self.evidence_digests) is not tuple or not self.evidence_digests:
            raise ValueError("checkpoint proof requires lower-authority evidence")
        evidence = tuple(sorted(self.evidence_digests))
        if len(evidence) != len(set(evidence)):
            raise ValueError("checkpoint evidence digests must be unique")
        for digest in evidence:
            require_sha256(digest, "checkpoint evidence digest")
        object.__setattr__(self, "evidence_digests", evidence)
        object.__setattr__(
            self,
            "proof_digest",
            canonical_digest(
                {
                    "schema": "noetrium.research-os-node-checkpoint.v1",
                    "execution_cut_id": self.execution_cut_id,
                    "graph_node_id": self.graph_node_id,
                    "semantic_digest": self.semantic_digest,
                    "lowering_digest": self.lowering_digest,
                    "authority_id": self.authority_id,
                    "machine_cut_digest": self.machine_cut.cut_digest,
                    "evidence_digests": evidence,
                }
            ),
        )

    def validate(
        self,
        node: object,
        lowering: object,
        *,
        execution_cut_id: str,
    ) -> None:
        from .research_os_graph import CompiledResearchOSGraphNode
        from .research_os_lowering import LoweredResearchOSGraphNode

        if type(node) is not CompiledResearchOSGraphNode:
            raise TypeError("checkpoint validation requires compiled graph node")
        if type(lowering) is not LoweredResearchOSGraphNode:
            raise TypeError("checkpoint validation requires lowered graph node")
        expected = (
            execution_cut_id,
            node.graph_node_id,
            node.semantic_digest,
            lowering.lowering_digest,
        )
        actual = (
            self.execution_cut_id,
            self.graph_node_id,
            self.semantic_digest,
            self.lowering_digest,
        )
        if actual != expected:
            raise ValueError("lower checkpoint proof identity drifted")


@dataclass(frozen=True, slots=True)
class ResearchOSGraphCheckpoint:
    """Durable acceleration proof for one exact ResearchGraph cut.

    This is never graph execution truth. It is a content-addressed proof bundle
    over an already-authoritative graph snapshot and lower Machine/reuse proofs.
    """

    execution_cut_id: str
    graph_digest: str
    research_revision_digest: str
    snapshot_generation: int
    control_generation: int
    control_phase: str
    selected_node_ids: tuple[str, ...]
    nodes: JsonValue
    checkpoint_digest: str = field(init=False)

    def __post_init__(self) -> None:
        require_sha256(self.execution_cut_id, "graph checkpoint execution_cut_id")
        require_sha256(self.graph_digest, "graph checkpoint graph_digest")
        require_sha256(
            self.research_revision_digest,
            "graph checkpoint research_revision_digest",
        )
        if type(self.snapshot_generation) is not int or self.snapshot_generation < 1:
            raise ValueError("graph checkpoint snapshot_generation must be positive")
        if type(self.control_generation) is not int or self.control_generation < 1:
            raise ValueError("graph checkpoint control_generation must be positive")
        _text(self.control_phase, "graph checkpoint control_phase")
        if type(self.selected_node_ids) is not tuple or not self.selected_node_ids:
            raise ValueError("graph checkpoint selected_node_ids must be non-empty tuple")
        ordered = tuple(sorted(_text(value, "graph checkpoint node id") for value in self.selected_node_ids))
        if len(ordered) != len(set(ordered)):
            raise ValueError("graph checkpoint selected_node_ids must be unique")
        object.__setattr__(self, "selected_node_ids", ordered)
        frozen_nodes = freeze_json(self.nodes)
        if not isinstance(frozen_nodes, tuple):
            raise TypeError("graph checkpoint nodes must be a JSON array")
        if len(frozen_nodes) != len(ordered):
            raise ValueError("graph checkpoint node proof count must match selection")
        for row in frozen_nodes:
            if not isinstance(row, Mapping):
                raise TypeError("graph checkpoint node proofs must be JSON objects")
        object.__setattr__(self, "nodes", frozen_nodes)
        object.__setattr__(self, "checkpoint_digest", canonical_digest(self.body()))

    @property
    def scope_digest(self) -> str:
        return canonical_digest(
            {
                "execution_cut_id": self.execution_cut_id,
                "selected_node_ids": self.selected_node_ids,
            }
        )

    def body(self) -> JsonObject:
        return {
            "schema": "noetrium.research-graph-checkpoint.v3",
            "execution_cut_id": self.execution_cut_id,
            "graph_digest": self.graph_digest,
            "research_revision_digest": self.research_revision_digest,
            "snapshot_generation": self.snapshot_generation,
            "control_generation": self.control_generation,
            "control_phase": self.control_phase,
            "selected_node_ids": self.selected_node_ids,
            "nodes": self.nodes,
        }

    def to_document(self) -> JsonObject:
        return {
            **self.body(),
            "checkpoint_digest": self.checkpoint_digest,
        }

    @classmethod
    def from_document(cls, document: JsonObject) -> "ResearchOSGraphCheckpoint":
        if document.get("schema") != "noetrium.research-graph-checkpoint.v3":
            raise ValueError("unsupported Research OS graph checkpoint schema")
        checkpoint = cls(
            execution_cut_id=str(document["execution_cut_id"]),
            graph_digest=str(document["graph_digest"]),
            research_revision_digest=str(document["research_revision_digest"]),
            snapshot_generation=document["snapshot_generation"],
            control_generation=document["control_generation"],
            control_phase=str(document["control_phase"]),
            selected_node_ids=tuple(document["selected_node_ids"]),
            nodes=document["nodes"],
        )
        if document.get("checkpoint_digest") != checkpoint.checkpoint_digest:
            raise ValueError("Research OS graph checkpoint digest mismatch")
        return checkpoint


class ResearchOSGraphCheckpointCorruptionError(ValueError):
    """A durable graph-checkpoint artifact failed canonical/integrity validation."""


@runtime_checkable
class ResearchOSGraphCheckpointStorePort(Protocol):
    def publish(
        self,
        checkpoint: ResearchOSGraphCheckpoint,
    ) -> ResearchOSGraphCheckpoint: ...

    def load(self, checkpoint_digest: str) -> ResearchOSGraphCheckpoint | None: ...

    def latest(
        self,
        execution_cut_id: str,
        selected_node_ids: tuple[str, ...],
    ) -> ResearchOSGraphCheckpoint | None: ...


class ResearchOSCheckpointIndeterminate(RuntimeError):
    """Lower authority cannot prove one exact durable Machine cut."""


@runtime_checkable
class ResearchOSNodeCheckpointPort(Protocol):
    def checkpoint_node(
        self,
        node: object,
        lowering: object,
        *,
        execution_cut_id: str,
        attempt_id: str,
    ) -> ResearchOSNodeCheckpointProof: ...


__all__ = [
    "ResearchOSCheckpointIndeterminate",
    "ResearchOSGraphCheckpoint",
    "ResearchOSGraphCheckpointCorruptionError",
    "ResearchOSGraphCheckpointStorePort",
    "ResearchOSNodeCheckpointPort",
    "ResearchOSNodeCheckpointProof",
]
