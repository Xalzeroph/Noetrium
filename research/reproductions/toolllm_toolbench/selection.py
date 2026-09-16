from __future__ import annotations

from dataclasses import dataclass, field

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityPort,
)
from noetrium_platform.evidence.data.projection.api import SemanticProjectionSnapshot
from noetrium_platform.evidence.data.query.api import (
    SemanticSimilarityQuery,
    SemanticSimilarityQueryPort,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest


@dataclass(frozen=True, slots=True)
class ToolLLMCapabilityView:
    """Exact retrieved capability set after authoritative descriptor re-materialization."""

    projection_digest: str
    source_cut_digest: str
    embedding_model_digest: str
    descriptors: tuple[CapabilityDescriptor, ...]
    view_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("projection_digest", "source_cut_digest", "embedding_model_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(f"ToolLLM capability view {name} must be lowercase SHA-256")
        if not isinstance(self.descriptors, tuple) or any(
            not isinstance(descriptor, CapabilityDescriptor) for descriptor in self.descriptors
        ):
            raise TypeError("ToolLLM capability view requires CapabilityDescriptor values")
        capability_ids = tuple(descriptor.capability_id for descriptor in self.descriptors)
        if len(set(capability_ids)) != len(capability_ids):
            raise ValueError("ToolLLM capability view cannot contain duplicate capabilities")
        object.__setattr__(
            self,
            "view_digest",
            canonical_digest(
                {
                    "projection_digest": self.projection_digest,
                    "source_cut_digest": self.source_cut_digest,
                    "embedding_model_digest": self.embedding_model_digest,
                    "descriptor_digests": [descriptor.digest() for descriptor in self.descriptors],
                }
            ),
        )


def retrieve_capability_view(
    *,
    snapshot: SemanticProjectionSnapshot,
    query_vector: tuple[float, ...],
    query_embedding_model_digest: str,
    capability_port: CapabilityPort,
    query_port: SemanticSimilarityQueryPort,
    limit: int = 5,
) -> ToolLLMCapabilityView:
    """Retrieve refs, then fail closed unless authoritative descriptors still match them.

    The semantic projection is disposable discovery state. The CapabilityPort remains
    the authority for the exact interface/schema exposed to the ToolLLM method. The
    query embedding identity is supplied independently and must match the pinned
    projection model identity before ranking can occur.
    """

    if not isinstance(snapshot, SemanticProjectionSnapshot):
        raise TypeError("ToolLLM capability retrieval requires SemanticProjectionSnapshot")
    if not isinstance(query_vector, tuple) or not query_vector:
        raise ValueError("ToolLLM query vector must be a non-empty tuple")
    if type(limit) is not int or not 1 <= limit <= 10_000:
        raise ValueError("ToolLLM retrieval limit must be in [1, 10000]")

    result = query_port.query(
        snapshot,
        SemanticSimilarityQuery(
            vector=query_vector,
            embedding_model_digest=query_embedding_model_digest,
            limit=limit,
        ),
    )
    descriptors: list[CapabilityDescriptor] = []
    for match in result.matches:
        descriptor = capability_port.describe(match.reference.record_id)
        if not isinstance(descriptor, CapabilityDescriptor):
            raise TypeError("CapabilityPort.describe must return CapabilityDescriptor")
        if descriptor.capability_id != match.reference.record_id:
            raise ValueError("retrieved capability reference resolved to another capability")
        if descriptor.digest() != match.reference.content_digest:
            raise ValueError("retrieved capability descriptor drifted from the pinned semantic projection")
        descriptors.append(descriptor)

    return ToolLLMCapabilityView(
        projection_digest=result.projection_digest,
        source_cut_digest=result.source_cut_digest,
        embedding_model_digest=result.embedding_model_digest,
        descriptors=tuple(descriptors),
    )


__all__ = ["ToolLLMCapabilityView", "retrieve_capability_view"]
