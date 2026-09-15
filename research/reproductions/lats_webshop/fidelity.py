from __future__ import annotations

from dataclasses import dataclass


LATS_WEBSHOP_AUDITED_COMMIT = "853d81614607dd27433faf17c7b0a7d660f95d22"


@dataclass(frozen=True, slots=True)
class LATSWebShopFidelity:
    source_repository: str = "https://github.com/andyz245/LanguageAgentTreeSearch"
    audited_commit: str = LATS_WEBSHOP_AUDITED_COMMIT
    source_artifact: str = "webshop/lats.py"
    environment: str = "webshop"
    think_prefix: str = "think["
    think_observation: str = "OK."
    success_reward: float = 1.0
    uct_exploration_constant: float = 2.0
    reflection_failed_trajectory_limit_exclusive: int = 4
    unique_failed_trajectory_limit: int = 3
    child_environment_semantics: str = "restore_parent_branch_state_before_candidate_action"

    def __post_init__(self) -> None:
        if len(self.audited_commit) != 40:
            raise ValueError("LATS audited commit must be a git SHA")
        if self.environment != "webshop" or self.success_reward != 1.0:
            raise ValueError("LATS WebShop environment semantics drifted")
        if self.uct_exploration_constant != 2.0:
            raise ValueError("LATS UCT exploration constant drifted")
        if (
            self.reflection_failed_trajectory_limit_exclusive,
            self.unique_failed_trajectory_limit,
        ) != (4, 3):
            raise ValueError("LATS reflection limits drifted")
        if self.child_environment_semantics != "restore_parent_branch_state_before_candidate_action":
            raise ValueError("LATS branch environment semantics drifted")


LATS_WEBSHOP_FIDELITY = LATSWebShopFidelity()


__all__ = ["LATS_WEBSHOP_AUDITED_COMMIT", "LATS_WEBSHOP_FIDELITY", "LATSWebShopFidelity"]
