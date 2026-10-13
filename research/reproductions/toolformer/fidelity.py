from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToolformerFidelity:
    publication_id: str = "d842425e4bf79ba039352da0f658a906"
    venue: str = "NeurIPS"
    year: int = 2023
    base_model: str = "GPT-J"
    base_model_parameters_billion: float = 6.7
    training_corpus: str = "subset of CCNet"
    tools: tuple[str, ...] = (
        "question_answering",
        "wikipedia_search",
        "calculator",
        "calendar",
        "machine_translation",
    )
    sampling_thresholds_are_tool_specific: bool = True
    filtering_thresholds_are_tool_specific: bool = True
    future_loss_raw_decay: float = 0.2
    training_batch_size: int = 128
    learning_rate: float = 1e-5
    linear_warmup_fraction: float = 0.10
    api_call_start_token: str = "<API>"
    api_call_end_token: str = "</API>"
    api_result_arrow: str = "→"
    evaluation_api_top_k: int = 10
    evaluation_max_api_calls_per_input: int = 1
    disabled_baseline_sets_api_probability_zero: bool = True

    def __post_init__(self) -> None:
        if self.tools != (
            "question_answering",
            "wikipedia_search",
            "calculator",
            "calendar",
            "machine_translation",
        ):
            raise ValueError("Toolformer paper tool set drifted")
        if self.training_batch_size != 128:
            raise ValueError("Toolformer batch size drifted")
        if self.learning_rate != 1e-5:
            raise ValueError("Toolformer learning rate drifted")
        if self.linear_warmup_fraction != 0.10:
            raise ValueError("Toolformer warmup fraction drifted")
        if self.future_loss_raw_decay != 0.2:
            raise ValueError("Toolformer future-loss weighting drifted")
        if self.evaluation_api_top_k != 10:
            raise ValueError("Toolformer evaluation API top-k drifted")
        if self.evaluation_max_api_calls_per_input != 1:
            raise ValueError("Toolformer evaluation max API calls drifted")
        if not self.disabled_baseline_sets_api_probability_zero:
            raise ValueError("Toolformer disabled baseline semantics drifted")


TOOLFORMER_FIDELITY = ToolformerFidelity()

__all__ = ["TOOLFORMER_FIDELITY", "ToolformerFidelity"]
