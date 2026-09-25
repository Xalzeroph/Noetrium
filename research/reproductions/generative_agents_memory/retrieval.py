from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .fidelity import GENERATIVE_AGENTS_RETRIEVAL_FIDELITY


@dataclass(frozen=True, slots=True)
class GenerativeMemoryNode:
    node_id: str
    embedding: tuple[float, ...]
    poignancy: float
    last_access_rank: int

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise ValueError("Generative Agents node_id is required")
        if not isinstance(self.embedding, tuple) or not self.embedding:
            raise ValueError("Generative Agents node embedding is required")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in self.embedding):
            raise ValueError("Generative Agents node embedding must contain finite numbers")
        if isinstance(self.poignancy, bool) or not isinstance(self.poignancy, (int, float)) or not math.isfinite(float(self.poignancy)):
            raise ValueError("Generative Agents poignancy must be finite")
        if type(self.last_access_rank) is not int or self.last_access_rank < 1:
            raise ValueError("Generative Agents last_access_rank must be positive")


@dataclass(frozen=True, slots=True)
class GenerativeRetrievalWeights:
    recency: float = 1.0
    relevance: float = 1.0
    importance: float = 1.0
    recency_decay: float = 0.99

    def __post_init__(self) -> None:
        for name in ("recency", "relevance", "importance", "recency_decay"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"Generative Agents {name} weight must be finite")
        if not 0.0 < self.recency_decay <= 1.0:
            raise ValueError("Generative Agents recency_decay must be in (0, 1]")


@dataclass(frozen=True, slots=True)
class GenerativeRetrievalScore:
    node: GenerativeMemoryNode
    recency: float
    relevance: float
    importance: float
    total: float


def _normalize(values: tuple[float, ...]) -> tuple[float, ...]:
    if not values:
        return ()
    low = min(values)
    high = max(values)
    if high == low:
        midpoint = (
            GENERATIVE_AGENTS_RETRIEVAL_FIDELITY.normalization_max
            - GENERATIVE_AGENTS_RETRIEVAL_FIDELITY.normalization_min
        ) / 2.0
        return tuple(midpoint for _ in values)
    span = high - low
    return tuple((value - low) / span for value in values)


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("Generative Agents embedding dimensions must match")
    left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
    right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        raise ValueError("Generative Agents cosine similarity rejects zero vectors")
    return sum(float(a) * float(b) for a, b in zip(left, right)) / (left_norm * right_norm)


def score_memories(
    nodes: tuple[GenerativeMemoryNode, ...],
    *,
    focal_embedding: tuple[float, ...],
    weights: GenerativeRetrievalWeights = GenerativeRetrievalWeights(),
) -> tuple[GenerativeRetrievalScore, ...]:
    """Reproduce the method-owned retrieval formula without owning storage/indexing."""

    if not nodes:
        return ()
    recency_raw = tuple(weights.recency_decay ** node.last_access_rank for node in nodes)
    importance_raw = tuple(float(node.poignancy) for node in nodes)
    relevance_raw = tuple(_cosine(node.embedding, focal_embedding) for node in nodes)
    recency = _normalize(recency_raw)
    importance = _normalize(importance_raw)
    relevance = _normalize(relevance_raw)
    fidelity = GENERATIVE_AGENTS_RETRIEVAL_FIDELITY
    rows = []
    for index, node in enumerate(nodes):
        total = (
            weights.recency * recency[index] * fidelity.global_recency_weight
            + weights.relevance * relevance[index] * fidelity.global_relevance_weight
            + weights.importance * importance[index] * fidelity.global_importance_weight
        )
        rows.append(GenerativeRetrievalScore(node, recency[index], relevance[index], importance[index], total))
    return tuple(sorted(rows, key=lambda row: (-row.total, row.node.node_id)))


def retrieve_top(
    nodes: tuple[GenerativeMemoryNode, ...],
    *,
    focal_embedding: tuple[float, ...],
    weights: GenerativeRetrievalWeights = GenerativeRetrievalWeights(),
    limit: int = GENERATIVE_AGENTS_RETRIEVAL_FIDELITY.default_retrieval_count,
) -> tuple[GenerativeRetrievalScore, ...]:
    if type(limit) is not int or limit <= 0:
        raise ValueError("Generative Agents retrieval limit must be positive")
    return score_memories(nodes, focal_embedding=focal_embedding, weights=weights)[:limit]


__all__ = [
    "GenerativeMemoryNode",
    "GenerativeRetrievalScore",
    "GenerativeRetrievalWeights",
    "retrieve_top",
    "score_memories",
]
