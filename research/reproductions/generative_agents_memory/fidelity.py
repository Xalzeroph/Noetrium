from __future__ import annotations

from dataclasses import dataclass


GENERATIVE_AGENTS_AUDITED_COMMIT = "fe05a71d3e4ed7d10bf68aa4eda6dd995ec070f4"


@dataclass(frozen=True, slots=True)
class GenerativeAgentsRetrievalFidelity:
    """Retrieval semantics pinned to the released Generative Agents code."""

    source_repository: str = "https://github.com/joonspk-research/generative_agents"
    audited_commit: str = GENERATIVE_AGENTS_AUDITED_COMMIT
    source_artifact: str = "reverie/backend_server/persona/cognitive_modules/retrieve.py"
    default_retrieval_count: int = 30
    global_recency_weight: float = 0.5
    global_relevance_weight: float = 3.0
    global_importance_weight: float = 2.0
    normalization_min: float = 0.0
    normalization_max: float = 1.0
    relevance_metric: str = "cosine_similarity"
    update_last_accessed_on_retrieval: bool = True

    def __post_init__(self) -> None:
        if len(self.audited_commit) != 40:
            raise ValueError("Generative Agents audited commit must be a git SHA")
        if self.default_retrieval_count != 30:
            raise ValueError("Generative Agents default retrieval count drifted")
        if (
            self.global_recency_weight,
            self.global_relevance_weight,
            self.global_importance_weight,
        ) != (0.5, 3.0, 2.0):
            raise ValueError("Generative Agents retrieval weights drifted")
        if (self.normalization_min, self.normalization_max) != (0.0, 1.0):
            raise ValueError("Generative Agents score normalization drifted")
        if self.relevance_metric != "cosine_similarity":
            raise ValueError("Generative Agents relevance metric drifted")
        if not self.update_last_accessed_on_retrieval:
            raise ValueError("Generative Agents retrieval must update last_accessed")


GENERATIVE_AGENTS_RETRIEVAL_FIDELITY = GenerativeAgentsRetrievalFidelity()


__all__ = [
    "GENERATIVE_AGENTS_AUDITED_COMMIT",
    "GENERATIVE_AGENTS_RETRIEVAL_FIDELITY",
    "GenerativeAgentsRetrievalFidelity",
]
