from __future__ import annotations

from dataclasses import dataclass


GORILLA_APIBENCH_AUDITED_COMMIT = "c849d11833ce0d401df4ab5a4d854167ad861684"


@dataclass(frozen=True, slots=True)
class GorillaAPIBenchReferenceFidelity:
    """Paper-era Gorilla retrieval/inference semantics audited from the official repo."""

    source_repository: str = "https://github.com/ShishirPatil/gorilla"
    audited_commit: str = GORILLA_APIBENCH_AUDITED_COMMIT
    gpt_retriever_source: str = "eval/retrievers/gpt.py"
    bm25_retriever_source: str = "eval/retrievers/bm25.py"
    inference_source: str = "eval/get_llm_responses_retriever.py"
    retrieval_modes: tuple[str, ...] = ("bm25", "gpt_embedding")
    default_top_k: int = 1
    embedding_similarity: str = "cosine"
    retrieved_api_is_injected_into_prompt: bool = True
    prompt_order: tuple[str, ...] = ("user_query", "retrieved_api_documentation")
    retriever_aware_training: bool = True
    retrieval_policy_owned_downstream: bool = True

    def __post_init__(self) -> None:
        if len(self.audited_commit) != 40:
            raise ValueError("Gorilla audited commit must be a git SHA")
        if self.retrieval_modes != ("bm25", "gpt_embedding"):
            raise ValueError("Gorilla retrieval modes drifted")
        if self.default_top_k != 1:
            raise ValueError("Gorilla paper-era inference top-k drifted")
        if self.embedding_similarity != "cosine":
            raise ValueError("Gorilla embedding retrieval similarity drifted")
        if self.prompt_order != ("user_query", "retrieved_api_documentation"):
            raise ValueError("Gorilla retrieved-API prompt composition drifted")
        if not (
            self.retrieved_api_is_injected_into_prompt
            and self.retriever_aware_training
            and self.retrieval_policy_owned_downstream
        ):
            raise ValueError("Gorilla retrieval/training ownership semantics drifted")


GORILLA_APIBENCH_REFERENCE_FIDELITY = GorillaAPIBenchReferenceFidelity()


__all__ = [
    "GORILLA_APIBENCH_AUDITED_COMMIT",
    "GORILLA_APIBENCH_REFERENCE_FIDELITY",
    "GorillaAPIBenchReferenceFidelity",
]
