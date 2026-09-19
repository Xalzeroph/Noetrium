from __future__ import annotations

import math

from noetrium_platform.evidence.data.projection.api import (
    SemanticProjectionEntry,
    SemanticProjectionSnapshot,
)
from noetrium_platform.evidence.data.query.api import (
    SemanticSimilarityMatch,
    SemanticSimilarityMetric,
    SemanticSimilarityQuery,
    SemanticSimilarityResult,
)


class SemanticRetrievalEngine:
    """Pure read-only semantic query engine over an immutable projection snapshot."""

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
        if query.embedding_model_digest != snapshot.embedding_model_digest:
            raise ValueError("semantic query embedding model does not match pinned projection")
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
            else:  # pragma: no cover - enum validation is fail-closed.
                raise ValueError("unsupported semantic similarity metric")
            scored.append((entry, score))

        if query.metric is SemanticSimilarityMetric.COSINE_SIMILARITY:
            scored.sort(key=lambda row: (-row[1], row[0].reference))
        else:
            scored.sort(key=lambda row: (row[1], row[0].reference))

        matches = tuple(
            SemanticSimilarityMatch(entry.reference, float(score), rank)
            for rank, (entry, score) in enumerate(scored[: query.limit], start=1)
        )
        return SemanticSimilarityResult(
            projection_digest=snapshot.projection_digest,
            source_cut_digest=snapshot.source_cut_digest,
            embedding_model_digest=snapshot.embedding_model_digest,
            metric=query.metric,
            candidate_count=len(entries),
            matches=matches,
        )


__all__ = ["SemanticRetrievalEngine"]
