from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityPort,
    CapabilitySelectionReference,
    CapabilitySelectionView,
    materialize_capability_selection_view,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256


class GorillaRetrieverMode(StrEnum):
    BM25 = "bm25"
    GPT_EMBEDDING = "gpt_embedding"


@dataclass(frozen=True, slots=True)
class GorillaRetrievalSelection:
    """Method-owned retrieval result before authoritative capability materialization."""

    mode: GorillaRetrieverMode
    source_cut_digest: str
    references: tuple[CapabilitySelectionReference, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.mode, GorillaRetrieverMode):
            raise TypeError("Gorilla retriever mode must be GorillaRetrieverMode")
        require_sha256(self.source_cut_digest, "Gorilla retrieval source_cut_digest")
        if not isinstance(self.references, tuple) or any(
            not isinstance(reference, CapabilitySelectionReference) for reference in self.references
        ):
            raise TypeError("Gorilla retrieval references must be typed capability references")
        capability_ids = tuple(reference.capability_id for reference in self.references)
        if len(set(capability_ids)) != len(capability_ids):
            raise ValueError("Gorilla retrieval references must be unique")

    def digest(self) -> str:
        return canonical_digest(
            {
                "mode": self.mode.value,
                "source_cut_digest": self.source_cut_digest,
                "reference_digests": [reference.digest() for reference in self.references],
            }
        )


def materialize_gorilla_capability_view(
    selection: GorillaRetrievalSelection,
    *,
    capability_port: CapabilityPort,
) -> CapabilitySelectionView:
    """Freeze Gorilla's retrieved API set without moving retrieval policy upstream."""

    if not isinstance(selection, GorillaRetrievalSelection):
        raise TypeError("Gorilla capability materialization requires GorillaRetrievalSelection")
    return materialize_capability_selection_view(
        selection.references,
        source_cut_digest=selection.source_cut_digest,
        selection_provenance_digest=selection.digest(),
        capability_port=capability_port,
    )


__all__ = [
    "GorillaRetrievalSelection",
    "GorillaRetrieverMode",
    "materialize_gorilla_capability_view",
]
