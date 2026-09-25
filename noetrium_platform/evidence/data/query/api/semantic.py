from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from noetrium_platform.evidence.data.projection.api import (
    SemanticProjectionSnapshot,
    SemanticSourceReference,
)
from noetrium_platform.foundation.kernel.kernel import require_sha256


class SemanticSimilarityMetric(StrEnum):
    COSINE_SIMILARITY = "cosine_similarity"
    SQUARED_L2_DISTANCE = "squared_l2_distance"


@dataclass(frozen=True, slots=True)
class SemanticSimilarityQuery:
    vector: tuple[float, ...]
    embedding_model_digest: str
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
        require_sha256(self.embedding_model_digest, "semantic query embedding_model_digest")
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

    def __post_init__(self) -> None:
        if not isinstance(self.reference, SemanticSourceReference):
            raise TypeError("semantic match reference must be SemanticSourceReference")
        if isinstance(self.score, bool) or not isinstance(self.score, (int, float)) or not math.isfinite(float(self.score)):
            raise ValueError("semantic match score must be finite")
        if type(self.rank) is not int or self.rank < 1:
            raise ValueError("semantic match rank must be positive")


@dataclass(frozen=True, slots=True)
class SemanticSimilarityResult:
    projection_digest: str
    source_cut_digest: str
    embedding_model_digest: str
    metric: SemanticSimilarityMetric
    candidate_count: int
    matches: tuple[SemanticSimilarityMatch, ...]

    def __post_init__(self) -> None:
        for name in ("projection_digest", "source_cut_digest", "embedding_model_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(f"semantic result {name} must be lowercase SHA-256")
        if not isinstance(self.metric, SemanticSimilarityMetric):
            raise TypeError("semantic result metric must be SemanticSimilarityMetric")
        if type(self.candidate_count) is not int or self.candidate_count < 0:
            raise ValueError("semantic result candidate_count must be non-negative")
        if not isinstance(self.matches, tuple) or any(
            not isinstance(match, SemanticSimilarityMatch) for match in self.matches
        ):
            raise TypeError("semantic result matches must contain SemanticSimilarityMatch")
        if len(self.matches) > self.candidate_count:
            raise ValueError("semantic result cannot return more matches than candidates")
        if tuple(match.rank for match in self.matches) != tuple(range(1, len(self.matches) + 1)):
            raise ValueError("semantic result match ranks must be contiguous from one")


@runtime_checkable
class SemanticSimilarityQueryPort(Protocol):
    def query(
        self,
        snapshot: SemanticProjectionSnapshot,
        query: SemanticSimilarityQuery,
    ) -> SemanticSimilarityResult: ...


__all__ = [
    "SemanticSimilarityMatch",
    "SemanticSimilarityMetric",
    "SemanticSimilarityQuery",
    "SemanticSimilarityQueryPort",
    "SemanticSimilarityResult",
]
