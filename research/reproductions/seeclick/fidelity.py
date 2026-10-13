from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SeeClickFidelity:
    source_repository: str = "https://github.com/njucckevin/SeeClick"
    venue: str = "ACL"
    year: int = 2024
    base_model: str = "Qwen-VL-Chat"
    model_parameters_billion: float = 9.6
    continual_pretraining_samples: int = 1_000_000
    coordinate_min: float = 0.0
    coordinate_max: float = 1.0
    coordinate_precision_decimals: int = 2
    grounding_tasks: tuple[str, ...] = (
        "text_2_point",
        "text_2_bbox",
        "point_2_text",
        "bbox_2_text",
    )
    optimizer: str = "AdamW"
    scheduler: str = "cosine"
    initial_learning_rate: float = 3e-5
    global_batch_size: int = 64
    training_gpu_count: int = 8
    training_gpu_type: str = "NVIDIA A100"
    approximate_training_hours: int = 24
    screenshots_only_for_agent: bool = True

    def __post_init__(self) -> None:
        if self.base_model != "Qwen-VL-Chat":
            raise ValueError("SeeClick base model drifted")
        if self.continual_pretraining_samples != 1_000_000:
            raise ValueError("SeeClick pretraining sample count drifted")
        if (self.coordinate_min, self.coordinate_max) != (0.0, 1.0):
            raise ValueError("SeeClick coordinate range drifted")
        if self.coordinate_precision_decimals != 2:
            raise ValueError("SeeClick coordinate precision drifted")
        if self.initial_learning_rate != 3e-5 or self.global_batch_size != 64:
            raise ValueError("SeeClick training configuration drifted")
        if not self.screenshots_only_for_agent:
            raise ValueError("SeeClick screenshot-only agent semantics drifted")


SEECLICK_FIDELITY = SeeClickFidelity()

__all__ = ["SEECLICK_FIDELITY", "SeeClickFidelity"]
