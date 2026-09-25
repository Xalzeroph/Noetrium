from __future__ import annotations

from dataclasses import dataclass


TOOLLLM_TOOLBENCH_AUDITED_COMMIT = "b2384c2a7f9c3e444a5e579596968ad88cd3201a"


@dataclass(frozen=True, slots=True)
class ToolLLMToolBenchReferenceFidelity:
    """Paper-era ToolLLM/ToolBench inference semantics audited from the official repo."""

    source_repository: str = "https://github.com/OpenBMB/ToolBench"
    audited_commit: str = TOOLLLM_TOOLBENCH_AUDITED_COMMIT
    retriever_source: str = "toolbench/inference/LLM/retriever.py"
    api_materialization_source: str = "toolbench/inference/Downstream_tasks/rapidapi.py"
    search_source: str = "toolbench/inference/Algorithms/DFS.py"
    default_retrieved_api_count: int = 5
    retrieval_similarity: str = "cosine"
    retrieved_identity_fields: tuple[str, ...] = (
        "category_name",
        "tool_name",
        "api_name",
    )
    authoritative_api_materialization: bool = True
    llm_function_schema_materialization: bool = True
    finish_function_injected: bool = True
    search_policy: str = "DFSDT"
    reference_inference_method: str = "DFS_woFilter_w2"
    single_chain_max_step: int = 12
    tree_beam_size: int = 2
    max_query_count: int = 200
    answer_count: int = 1
    with_filter: bool = False
    final_answer_back_length: int = 2
    prune_back_length: int = 2
    finish_return_types: tuple[str, str] = ("give_answer", "give_up_and_restart")
    branch_local_io_state: bool = True

    def __post_init__(self) -> None:
        if len(self.audited_commit) != 40:
            raise ValueError("ToolLLM audited commit must be a git SHA")
        if self.default_retrieved_api_count != 5:
            raise ValueError("ToolLLM default retrieval width drifted")
        if self.retrieval_similarity != "cosine":
            raise ValueError("ToolLLM retrieval similarity drifted")
        if self.retrieved_identity_fields != ("category_name", "tool_name", "api_name"):
            raise ValueError("ToolLLM retrieved API identity fields drifted")
        if not (
            self.authoritative_api_materialization
            and self.llm_function_schema_materialization
            and self.finish_function_injected
            and self.branch_local_io_state
        ):
            raise ValueError("ToolLLM inference semantics drifted")
        if self.search_policy != "DFSDT":
            raise ValueError("ToolLLM search policy drifted")
        if self.reference_inference_method != "DFS_woFilter_w2":
            raise ValueError("ToolLLM reference inference lane drifted")
        if (
            self.single_chain_max_step,
            self.tree_beam_size,
            self.max_query_count,
            self.answer_count,
            self.final_answer_back_length,
            self.prune_back_length,
        ) != (12, 2, 200, 1, 2, 2):
            raise ValueError("ToolLLM DFSDT inference constants drifted")
        if self.with_filter:
            raise ValueError("ToolLLM reference DFS_woFilter_w2 lane must not rank-filter")
        if self.finish_return_types != ("give_answer", "give_up_and_restart"):
            raise ValueError("ToolLLM Finish return types drifted")


TOOLLLM_TOOLBENCH_REFERENCE_FIDELITY = ToolLLMToolBenchReferenceFidelity()


__all__ = [
    "TOOLLLM_TOOLBENCH_AUDITED_COMMIT",
    "TOOLLLM_TOOLBENCH_REFERENCE_FIDELITY",
    "ToolLLMToolBenchReferenceFidelity",
]
