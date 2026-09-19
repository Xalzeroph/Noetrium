from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VCAReferenceFidelity:
    paper_uri: str = (
        "https://openaccess.thecvf.com/content/ICCV2025/html/"
        "Yang_VCA_Video_Curious_Agent_for_Long_Video_Understanding_ICCV_2025_paper.html"
    )
    venue: str = "ICCV 2025"
    training_free: bool = True
    shared_vlm_for_reward_and_exploration: bool = True
    tree_search: bool = True
    reward_history_conditioning: bool = True
    fixed_size_memory: bool = True
    non_greedy_segment_choice: bool = True
    temperature: float = 0.5
    reference_model: str = "gpt-4o-august-2024"
    egoschema_memory_frames: int = 8
    lvbench_memory_frames: int = 16
    egoschema_task_count: int = 500
    lvbench_task_count: int = 1549
    mmbench_video_task_count: int = 1998
    videomme_long_task_count: int = 900
    egoschema_reported_accuracy: float = 0.736
    egoschema_reported_average_frames: float = 7.2
    lvbench_reported_accuracy: float = 0.413
    lvbench_reported_average_frames: float = 20.0

    def __post_init__(self) -> None:
        if not all(
            (
                self.training_free,
                self.shared_vlm_for_reward_and_exploration,
                self.tree_search,
                self.reward_history_conditioning,
                self.fixed_size_memory,
                self.non_greedy_segment_choice,
            )
        ):
            raise ValueError("VCA core paper semantics drifted")
        if self.temperature != 0.5:
            raise ValueError("VCA paper temperature drifted")
        if self.egoschema_memory_frames != 8 or self.lvbench_memory_frames != 16:
            raise ValueError("VCA memory-buffer sizes drifted")
        if self.egoschema_task_count != 500:
            raise ValueError("VCA EgoSchema evaluation count drifted")


VCA_REFERENCE_FIDELITY = VCAReferenceFidelity()


__all__ = ["VCA_REFERENCE_FIDELITY", "VCAReferenceFidelity"]
