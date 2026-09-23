from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.execution.graph.api import (
    ResearchGraphReconciliationDisposition,
)

from .research_os_graph import CompiledResearchOSGraphNode
from .research_os_lowering import LoweredResearchOSGraphNode


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field_name} must be canonical non-empty text")
    return value


@dataclass(frozen=True, slots=True)
class ResearchOSNodeReconciliationProof:
    """Lower-authority proof for resolving one uncertain graph attempt."""

    execution_cut_id: str
    graph_node_id: str
    semantic_digest: str
    lowering_digest: str
    attempt_id: str
    disposition: ResearchGraphReconciliationDisposition
    authority_id: str
    evidence_digests: tuple[str, ...]
    failure_type: str | None = None
    failure_message: str | None = None
    proof_digest: str = field(init=False)

    def __post_init__(self) -> None:
        require_sha256(self.execution_cut_id, "reconciliation execution_cut_id")
        _text(self.graph_node_id, "reconciliation graph_node_id")
        require_sha256(self.semantic_digest, "reconciliation semantic_digest")
        require_sha256(self.lowering_digest, "reconciliation lowering_digest")
        _text(self.attempt_id, "reconciliation attempt_id")
        if not isinstance(self.disposition, ResearchGraphReconciliationDisposition):
            raise TypeError("reconciliation disposition must be typed")
        _text(self.authority_id, "reconciliation authority_id")
        if type(self.evidence_digests) is not tuple or not self.evidence_digests:
            raise ValueError("reconciliation proof requires lower-authority evidence")
        evidence = tuple(sorted(self.evidence_digests))
        if len(evidence) != len(set(evidence)):
            raise ValueError("reconciliation evidence digests must be unique")
        for digest in evidence:
            require_sha256(digest, "reconciliation evidence digest")
        object.__setattr__(self, "evidence_digests", evidence)

        if self.disposition is ResearchGraphReconciliationDisposition.FAILED:
            _text(self.failure_type, "reconciliation failure_type")
            _text(self.failure_message, "reconciliation failure_message")
        elif self.failure_type is not None or self.failure_message is not None:
            raise ValueError(
                "only failed reconciliation may carry failure metadata"
            )

        object.__setattr__(
            self,
            "proof_digest",
            canonical_digest(
                {
                    "schema": "noetrium.research-os-node-reconciliation.v1",
                    "execution_cut_id": self.execution_cut_id,
                    "graph_node_id": self.graph_node_id,
                    "semantic_digest": self.semantic_digest,
                    "lowering_digest": self.lowering_digest,
                    "attempt_id": self.attempt_id,
                    "disposition": self.disposition.value,
                    "authority_id": self.authority_id,
                    "evidence_digests": evidence,
                    "failure_type": self.failure_type,
                    "failure_message": self.failure_message,
                }
            ),
        )

    def validate(
        self,
        node: CompiledResearchOSGraphNode,
        lowering: LoweredResearchOSGraphNode,
        *,
        execution_cut_id: str,
        attempt_id: str,
    ) -> None:
        if type(node) is not CompiledResearchOSGraphNode:
            raise TypeError("reconciliation validation requires compiled graph node")
        if type(lowering) is not LoweredResearchOSGraphNode:
            raise TypeError("reconciliation validation requires lowered graph node")
        expected = (
            execution_cut_id,
            node.graph_node_id,
            node.semantic_digest,
            lowering.lowering_digest,
            attempt_id,
        )
        actual = (
            self.execution_cut_id,
            self.graph_node_id,
            self.semantic_digest,
            self.lowering_digest,
            self.attempt_id,
        )
        if actual != expected:
            raise ValueError("lower reconciliation proof identity drifted")


class ResearchOSReconciliationIndeterminate(RuntimeError):
    """Lower authority cannot yet prove a safe graph disposition."""


@runtime_checkable
class ResearchOSNodeReconciliationPort(Protocol):
    def reconcile_node(
        self,
        node: CompiledResearchOSGraphNode,
        lowering: LoweredResearchOSGraphNode,
        *,
        execution_cut_id: str,
        attempt_id: str,
    ) -> ResearchOSNodeReconciliationProof: ...


__all__ = [
    "ResearchOSNodeReconciliationPort",
    "ResearchOSNodeReconciliationProof",
    "ResearchOSReconciliationIndeterminate",
]
