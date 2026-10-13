from __future__ import annotations

from dataclasses import dataclass

from .source import SOURCE_NEURIPS_2022_PAPER


@dataclass(frozen=True, slots=True)
class ChainOfThoughtGSM8KFidelity:
    """NeurIPS-2022 8-shot arithmetic chain-of-thought prompting semantics."""

    publication = SOURCE_NEURIPS_2022_PAPER
    benchmark_id: str = "gsm8k"
    benchmark_split: str = "test"
    exemplar_count: int = 8
    exemplar_source: str = "NeurIPS 2022 Appendix Table 20"
    prompt_mode: str = "few_shot_chain_of_thought"
    decoding: str = "greedy"
    samples_per_task: int = 1
    paper_reference_model: str = "PaLM-540B"
    paper_gsm8k_accuracy_percent: float = 56.9
    paper_standard_prompt_accuracy_percent: float = 17.9
    calculator_enabled: bool = False

    def __post_init__(self) -> None:
        if self.exemplar_count != 8:
            raise ValueError("CoT GSM8K paper protocol requires eight exemplars")
        if self.decoding != "greedy" or self.samples_per_task != 1:
            raise ValueError("CoT GSM8K baseline requires one greedy reasoning path")
        if self.calculator_enabled:
            raise ValueError("primary CoT GSM8K lane excludes the calculator variant")


CHAIN_OF_THOUGHT_GSM8K_FIDELITY = ChainOfThoughtGSM8KFidelity()

__all__ = ["CHAIN_OF_THOUGHT_GSM8K_FIDELITY", "ChainOfThoughtGSM8KFidelity"]
