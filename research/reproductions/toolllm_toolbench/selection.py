from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityPort,
    CapabilitySelectionReference,
    CapabilitySelectionView,
    materialize_capability_selection_view,
)
from noetrium_platform.evidence.data.projection.api import SemanticProjectionSnapshot
from noetrium_platform.evidence.data.query.api import (
    SemanticSimilarityQuery,
    SemanticSimilarityQueryPort,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256


@dataclass(frozen=True, slots=True)
class ToolLLMCapabilityView:
    """ToolLLM-specific semantic provenance around the generic immutable capability view."""

    projection_digest: str
    embedding_model_digest: str
    selection_view: CapabilitySelectionView

    def __post_init__(self) -> None:
        require_sha256(self.projection_digest, "ToolLLM capability view projection_digest")
        require_sha256(
            self.embedding_model_digest,
            "ToolLLM capability view embedding_model_digest",
        )
        if not isinstance(self.selection_view, CapabilitySelectionView):
            raise TypeError("ToolLLM capability view requires CapabilitySelectionView")

    @property
    def source_cut_digest(self) -> str:
        return self.selection_view.source_cut_digest

    @property
    def descriptors(self) -> tuple[CapabilityDescriptor, ...]:
        return self.selection_view.descriptors

    @property
    def view_digest(self) -> str:
        return canonical_digest(
            {
                "projection_digest": self.projection_digest,
                "embedding_model_digest": self.embedding_model_digest,
                "selection_view_digest": self.selection_view.view_digest,
            }
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
    """Semantic-select refs, then freeze exact authoritative descriptors generically.

    ToolLLM owns semantic selection policy. The platform capability-selection view
    owns only the immutable selected surface and descriptor drift checks.
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
    references = tuple(
        CapabilitySelectionReference(
            capability_id=match.reference.record_id,
            descriptor_digest=match.reference.content_digest,
        )
        for match in result.matches
    )
    selection_provenance_digest = canonical_digest(
        {
            "projection_digest": result.projection_digest,
            "source_cut_digest": result.source_cut_digest,
            "embedding_model_digest": result.embedding_model_digest,
            "metric": result.metric.value,
            "candidate_count": result.candidate_count,
            "matches": [
                {
                    "reference_digest": reference.digest(),
                    "score": match.score,
                    "rank": match.rank,
                }
                for reference, match in zip(references, result.matches)
            ],
        }
    )
    selection_view = materialize_capability_selection_view(
        references,
        source_cut_digest=result.source_cut_digest,
        selection_provenance_digest=selection_provenance_digest,
        capability_port=capability_port,
    )
    return ToolLLMCapabilityView(
        projection_digest=result.projection_digest,
        embedding_model_digest=result.embedding_model_digest,
        selection_view=selection_view,
    )


__all__ = ["ToolLLMCapabilityView", "retrieve_capability_view"]
