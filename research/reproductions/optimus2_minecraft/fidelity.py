from __future__ import annotations

from dataclasses import dataclass

from .source import OPTIMUS2_PAPER_REPOSITORY_COMMIT


@dataclass(frozen=True, slots=True)
class Optimus2ReferenceFidelity:
    venue: str = "CVPR 2025"
    paper_repository_commit: str = OPTIMUS2_PAPER_REPOSITORY_COMMIT
    official_repository_contains_executable_code: bool = False

    high_level_planner: str = "multimodal_large_language_model"
    low_level_policy: str = "goal_observation_action_conditioned_policy"
    goap_action_guided_behavior_encoder: bool = True
    goap_action_observation_causal_modeling: bool = True
    goap_historical_observation_action_interaction: bool = True
    goap_fixed_length_behavior_tokens: bool = True
    goap_language_behavior_alignment: bool = True
    goap_autoregressive_action_prediction: bool = True

    mgoa_video_count: int = 25_000
    mgoa_atomic_task_count: int = 8
    mgoa_goal_observation_action_pairs_approx: int = 30_000_000

    evaluation_scopes: tuple[str, ...] = (
        "atomic_tasks",
        "long_horizon_tasks",
        "open_ended_instruction_tasks",
    )
    atomic_task_metric: str = "average_reward"
    long_horizon_metric: str = "average_success_rate"
    open_ended_instruction_metric: str = "average_success_rate"

    def __post_init__(self) -> None:
        if len(self.paper_repository_commit) != 40:
            raise ValueError("Optimus-2 source cut must be a git SHA")
        if self.official_repository_contains_executable_code:
            raise ValueError(
                "Optimus-2 paper repository must remain non-executable"
            )
        if not all(
            (
                self.goap_action_guided_behavior_encoder,
                self.goap_action_observation_causal_modeling,
                self.goap_historical_observation_action_interaction,
                self.goap_fixed_length_behavior_tokens,
                self.goap_language_behavior_alignment,
                self.goap_autoregressive_action_prediction,
            )
        ):
            raise ValueError("Optimus-2 GOAP architecture semantics drifted")
        if (
            self.mgoa_video_count,
            self.mgoa_atomic_task_count,
            self.mgoa_goal_observation_action_pairs_approx,
        ) != (25_000, 8, 30_000_000):
            raise ValueError("Optimus-2 MGOA headline statistics drifted")


OPTIMUS2_REFERENCE_FIDELITY = Optimus2ReferenceFidelity()


__all__ = [
    "OPTIMUS2_REFERENCE_FIDELITY",
    "Optimus2ReferenceFidelity",
]
