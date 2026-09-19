from __future__ import annotations

from dataclasses import dataclass

from .source import (
    VIMA_BENCH_AUDITED_COMMIT,
    VIMA_POLICY_AUDITED_COMMIT,
)


VIMA_TASKS = (
    "visual_manipulation",
    "scene_understanding",
    "rotate",
    "rearrange",
    "rearrange_then_restore",
    "novel_adj",
    "novel_noun",
    "novel_adj_and_noun",
    "twist",
    "follow_motion",
    "follow_order",
    "sweep_without_exceeding",
    "sweep_without_touching",
    "same_texture",
    "same_shape",
    "manipulate_old_neighbor",
    "pick_in_order_then_restore",
)

VIMA_EVAL_PARTITIONS = (
    "placement_generalization",
    "combinatorial_generalization",
    "novel_object_generalization",
    "novel_task_generalization",
)


@dataclass(frozen=True, slots=True)
class VimaReferenceFidelity:
    policy_commit: str = VIMA_POLICY_AUDITED_COMMIT
    benchmark_commit: str = VIMA_BENCH_AUDITED_COMMIT

    prompt_interleaves_text_and_visual_tokens: bool = True
    object_centric_prompt_images: bool = True
    object_centric_observations: bool = True
    observation_views: tuple[str, ...] = ("front", "top")
    observation_modalities: tuple[str, ...] = ("rgb", "segm", "ee")
    object_crop_resolution: int = 32

    autoregressive_action_history: bool = True
    prompt_cross_attention: bool = True
    observation_action_interleaving: bool = True

    pose_position_bins: tuple[int, int] = (50, 100)
    pose_rotation_bins: tuple[int, int, int, int] = (50, 50, 50, 50)
    position_action_dimensions: int = 2
    rotation_action_dimensions: int = 4
    pick_and_place_poses: int = 2

    environment_position_low: tuple[float, float] = (0.25, -0.5)
    environment_position_high: tuple[float, float] = (0.75, 0.5)
    environment_rotation_low: float = -1.0
    environment_rotation_high: float = 1.0

    reset_retry_limit: int = 10
    episode_bonus_steps: int = 2
    benchmark_task_count: int = 17
    evaluation_level_count: int = 4
    expert_trajectory_scale: str = "650K"

    def __post_init__(self) -> None:
        if len(self.policy_commit) != 40 or len(self.benchmark_commit) != 40:
            raise ValueError("VIMA source commits must be git SHAs")
        if self.observation_views != ("front", "top"):
            raise ValueError("VIMA camera view order drifted")
        if self.observation_modalities != ("rgb", "segm", "ee"):
            raise ValueError("VIMA observation modalities drifted")
        if self.object_crop_resolution != 32:
            raise ValueError("VIMA object crop resolution drifted")
        if self.pose_position_bins != (50, 100):
            raise ValueError("VIMA position action bins drifted")
        if self.pose_rotation_bins != (50, 50, 50, 50):
            raise ValueError("VIMA rotation action bins drifted")
        if self.pick_and_place_poses != 2:
            raise ValueError("VIMA pick/place action structure drifted")
        if (self.reset_retry_limit, self.episode_bonus_steps) != (10, 2):
            raise ValueError("VIMA evaluation wrapper semantics drifted")
        if self.benchmark_task_count != len(VIMA_TASKS):
            raise ValueError("VIMA benchmark task count drifted")
        if self.evaluation_level_count != len(VIMA_EVAL_PARTITIONS):
            raise ValueError("VIMA evaluation partition count drifted")
        if not all((
            self.prompt_interleaves_text_and_visual_tokens,
            self.object_centric_prompt_images,
            self.object_centric_observations,
            self.autoregressive_action_history,
            self.prompt_cross_attention,
            self.observation_action_interleaving,
        )):
            raise ValueError("VIMA core policy semantics drifted")


VIMA_REFERENCE_FIDELITY = VimaReferenceFidelity()


__all__ = [
    "VIMA_EVAL_PARTITIONS",
    "VIMA_REFERENCE_FIDELITY",
    "VIMA_TASKS",
    "VimaReferenceFidelity",
]
