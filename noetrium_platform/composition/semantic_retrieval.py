from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256


class SemanticSimilarityMetric(StrEnum):
    COSINE_SIMILARITY = "cosine_similarity"
    SQUARED_L2_DISTANCE = "squared_l2_distance"


@dataclass(frozen=True, slots=True, order=True)
class SemanticSourceReference:
    """Stable pointer back to authoritative source content; never the content itself."""

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
    """Immutable, rebuildable projection over one exact source cut.

    The snapshot owns no source content and has no write API. It may be discarded
    and rebuilt from authoritative records plus a pinned embedding model.
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


@dataclass(frozen=True, slots=True)
class SemanticSimilarityQuery:
    vector: tuple[float, ...]
    metric: SemanticSimilarityMetric = SemanticSimilarityMetric.COSINE_SIMILARITY
    limit: int = 10
    candidates: tuple[SemanticSourceReference, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.metric, SemanticSimilarityMetric):
            raise TypeError("semantic query metric must be SemanticSimilarityMetric")
        if not isinstance(self.vector, tuple) or not self.vector:
            raise ValueError("semantic query vector must be non-empty")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in self.vector
        ):
            raise ValueError("semantic query vector must contain finite numbers")
        if type(self.limit) is not int or not 1 <= self.limit <= 10_000:
            raise ValueError("semantic query limit must be in [1, 10000]")
        if not isinstance(self.candidates, tuple) or any(
            not isinstance(reference, SemanticSourceReference) for reference in self.candidates
        ):
            raise TypeError("semantic query candidates must contain SemanticSourceReference")
        if len(set(self.candidates)) != len(self.candidates):
            raise ValueError("semantic query candidates must be unique")


@dataclass(frozen=True, slots=True)
class SemanticSimilarityMatch:
    reference: SemanticSourceReference
    score: float
    rank: int


@dataclass(frozen=True, slots=True)
class SemanticSimilarityResult:
    projection_digest: str
    source_cut_digest: str
    metric: SemanticSimilarityMetric
    candidate_count: int
    matches: tuple[SemanticSimilarityMatch, ...]


class SemanticRetrievalEngine:
    """Pure query engine over an immutable semantic projection snapshot."""

    @staticmethod
    def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
        left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
        right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
        if left_norm == 0.0 or right_norm == 0.0:
            raise ValueError("cosine semantic retrieval rejects zero vectors")
        return sum(float(a) * float(b) for a, b in zip(left, right)) / (left_norm * right_norm)

    @staticmethod
    def _squared_l2(left: tuple[float, ...], right: tuple[float, ...]) -> float:
        return sum((float(a) - float(b)) ** 2 for a, b in zip(left, right))

    def query(
        self,
        snapshot: SemanticProjectionSnapshot,
        query: SemanticSimilarityQuery,
    ) -> SemanticSimilarityResult:
        if not isinstance(snapshot, SemanticProjectionSnapshot):
            raise TypeError("semantic retrieval requires SemanticProjectionSnapshot")
        if not isinstance(query, SemanticSimilarityQuery):
            raise TypeError("semantic retrieval requires SemanticSimilarityQuery")
        if len(query.vector) != snapshot.dimension:
            raise ValueError("semantic query vector dimension does not match projection")
        index = {entry.reference: entry for entry in snapshot.entries}
        if query.candidates:
            missing = tuple(reference for reference in query.candidates if reference not in index)
            if missing:
                raise ValueError("semantic query candidate is absent from the pinned projection")
            entries = tuple(index[reference] for reference in query.candidates)
        else:
            entries = snapshot.entries
        scored: list[tuple[SemanticProjectionEntry, float]] = []
        for entry in entries:
            if query.metric is SemanticSimilarityMetric.COSINE_SIMILARITY:
                score = self._cosine(query.vector, entry.embedding)
            elif query.metric is SemanticSimilarityMetric.SQUARED_L2_DISTANCE:
                score = self._squared_l2(query.vector, entry.embedding)
            else:  # pragma: no cover - enum validation keeps this fail-closed.
                raise ValueError("unsupported semantic similarity metric")
            scored.append((entry, score))
        reverse = query.metric is SemanticSimilarityMetric.COSINE_SIMILARITY
        if reverse:
            scored.sort(key=lambda row: (-row[1], row[0].reference))
        else:
            scored.sort(key=lambda row: (row[1], row[0].reference))
        matches = tuple(
            SemanticSimilarityMatch(entry.reference, float(score), rank)
            for rank, (entry, score) in enumerate(scored[: query.limit], start=1)
        )
        return SemanticSimilarityResult(
            snapshot.projection_digest,
            snapshot.source_cut_digest,
            query.metric,
            len(entries),
            matches,
        )


__all__ = [
    "SemanticProjectionEntry",
    "SemanticProjectionSnapshot",
    "SemanticRetrievalEngine",
    "SemanticSimilarityMatch",
    "SemanticSimilarityMetric",
    "SemanticSimilarityQuery",
    "SemanticSimilarityResult",
    "SemanticSourceReference",
]
