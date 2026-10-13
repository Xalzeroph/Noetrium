from __future__ import annotations

from dataclasses import dataclass

from .source import SOURCE_ICLR_2023_PAPER


@dataclass(frozen=True, slots=True)
class SelfConsistencyGSM8KFidelity:
    """ICLR-2023 PaLM-540B GSM8K self-consistency decoding semantics."""

    publication = SOURCE_ICLR_2023_PAPER
    benchmark_id: str = "gsm8k"
    benchmark_split: str = "test"
    cot_exemplar_count: int = 8
    cot_prompt_source: str = "same arithmetic CoT prompts as Wei et al. 2022"
    reasoning_path_count: int = 40
    temperature: float = 0.7
    top_k: int = 40
    aggregation: str = "marginalize_final_answer_frequency"
    paper_repetitions: int = 10
    paper_reference_model: str = "PaLM-540B"
    paper_gsm8k_self_consistency_percent: float = 74.4
    paper_gsm8k_greedy_cot_percent: float = 56.5

    def __post_init__(self) -> None:
        if self.cot_exemplar_count != 8:
            raise ValueError("Self-Consistency GSM8K uses the eight-example CoT prompt")
        if self.reasoning_path_count != 40:
            raise ValueError("paper result protocol samples 40 reasoning paths")
        if self.temperature != 0.7 or self.top_k != 40:
            raise ValueError("PaLM-540B paper sampling profile requires T=0.7 and top-k=40")
        if self.paper_repetitions != 10:
            raise ValueError("reported sampled results are averaged over ten runs")


SELF_CONSISTENCY_GSM8K_FIDELITY = SelfConsistencyGSM8KFidelity()

__all__ = [
    "SELF_CONSISTENCY_GSM8K_FIDELITY",
    "SelfConsistencyGSM8KFidelity",
]
