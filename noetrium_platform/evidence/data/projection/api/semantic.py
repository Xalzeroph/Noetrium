from __future__ import annotations

import math
from dataclasses import dataclass, field

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256


@dataclass(frozen=True, slots=True, order=True)
class SemanticSourceReference:
    """Stable pointer to authoritative source content, never the content itself."""

    source_id: str
    record_id: str
    content_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or not self.source_id.strip():
            raise ValueError("semantic source_id is required")
        if not isinstance(self.record_id, str) or not self.record_id.strip():
            raise ValueError("semantic record_id is required")
        require_sha256(self.content_digest, "semantic content_digest")


@dataclass(frozen=True, slots=True)
class SemanticProjectionEntry:
    """One disposable vector projection entry bound to source identity."""

    reference: SemanticSourceReference
    embedding: tuple[float, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.reference, SemanticSourceReference):
            raise TypeError("semantic projection entry requires SemanticSourceReference")
        if not isinstance(self.embedding, tuple) or not self.embedding:
            raise ValueError("semantic projection embedding must be a non-empty tuple")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in self.embedding
        ):
            raise ValueError("semantic projection embedding must contain finite numbers")


@dataclass(frozen=True, slots=True)
class SemanticProjectionSnapshot:
    """Immutable rebuildable semantic projection over one exact authoritative source cut.

    A snapshot stores only source references, vectors and provenance. It deliberately
    owns no source text/content and exposes no source mutation API.
    """

    projection_id: str
    projection_version: str
    source_cut_digest: str
    embedding_model_digest: str
    entries: tuple[SemanticProjectionEntry, ...]
    dimension: int = field(init=False)
    projection_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("projection_id", "projection_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"semantic {name} is required")
        require_sha256(self.source_cut_digest, "semantic source_cut_digest")
        require_sha256(self.embedding_model_digest, "semantic embedding_model_digest")
        if not isinstance(self.entries, tuple) or not self.entries:
            raise ValueError("semantic projection snapshot requires entries")
        if any(not isinstance(entry, SemanticProjectionEntry) for entry in self.entries):
            raise TypeError("semantic projection snapshot contains invalid entries")

        references = tuple(entry.reference for entry in self.entries)
        if len(set(references)) != len(references):
            raise ValueError("semantic projection snapshot contains duplicate source references")
        dimension = len(self.entries[0].embedding)
        if any(len(entry.embedding) != dimension for entry in self.entries):
            raise ValueError("semantic projection embedding dimensions disagree")

        ordered = tuple(sorted(self.entries, key=lambda entry: entry.reference))
        object.__setattr__(self, "entries", ordered)
        object.__setattr__(self, "dimension", dimension)
        object.__setattr__(
            self,
            "projection_digest",
            canonical_digest(
                {
                    "projection_id": self.projection_id,
                    "projection_version": self.projection_version,
                    "source_cut_digest": self.source_cut_digest,
                    "embedding_model_digest": self.embedding_model_digest,
                    "entries": [
                        {
                            "source_id": entry.reference.source_id,
                            "record_id": entry.reference.record_id,
                            "content_digest": entry.reference.content_digest,
                            "embedding": list(entry.embedding),
                        }
                        for entry in ordered
                    ],
                }
            ),
        )


__all__ = [
    "SemanticProjectionEntry",
    "SemanticProjectionSnapshot",
    "SemanticSourceReference",
]
