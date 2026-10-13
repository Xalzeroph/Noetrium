from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CogAgentFidelity:
    venue: str = "CVPR"
    year: int = 2024
    model_parameters_billion: int = 18
    visual_parameters_billion: int = 11
    language_parameters_billion: int = 7
    input_resolution: tuple[int, int] = (1120, 1120)
    low_resolution_encoder: bool = True
    high_resolution_encoder: bool = True
    gui_input_representation: str = "screenshot_only"
    gui_benchmarks: tuple[str, ...] = ("Mind2Web", "AITW")
    mind2web_operation_types: tuple[str, ...] = ("CLICK", "TYPE", "SELECT")

    def __post_init__(self) -> None:
        if self.model_parameters_billion != 18:
            raise ValueError("CogAgent model-size identity drifted")
        if (self.visual_parameters_billion, self.language_parameters_billion) != (11, 7):
            raise ValueError("CogAgent parameter partition drifted")
        if self.input_resolution != (1120, 1120):
            raise ValueError("CogAgent paper input resolution drifted")
        if not self.low_resolution_encoder or not self.high_resolution_encoder:
            raise ValueError("CogAgent dual-resolution vision semantics drifted")
        if self.gui_input_representation != "screenshot_only":
            raise ValueError("CogAgent GUI input representation drifted")


COGAGENT_FIDELITY = CogAgentFidelity()

__all__ = ["COGAGENT_FIDELITY", "CogAgentFidelity"]
