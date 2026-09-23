from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import (
    MachineCut,
    canonical_digest,
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
    ) -> ResearchOSNodeCheckpointProof: ...


__all__ = [
    "ResearchOSCheckpointIndeterminate",
    "ResearchOSNodeCheckpointPort",
    "ResearchOSNodeCheckpointProof",
]
