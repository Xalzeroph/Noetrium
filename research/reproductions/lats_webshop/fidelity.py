from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LatsWebshopFidelity:
    """Matched-stack protocol extracted from the official LATS WebShop implementation."""

    source_repository: str = "https://github.com/andyz245/LanguageAgentTreeSearch"
    source_artifact: str = "webshop/lats.py"
    max_iterations: int = 50
    max_depth: int = 15
    root_expansion_multiplier: int = 2
    rollout_candidate_count: int = 5
    success_reward: float = 1.0
    uses_uct_selection: bool = True
    uses_lm_value_function: bool = True
    uses_failed_trajectory_reflection: bool = True
    requires_branchable_environment_state: bool = True

    def __post_init__(self) -> None:
        if self.max_iterations != 50 or self.max_depth != 15:
            raise ValueError("matched LATS WebShop reproduction requires 50 iterations and depth 15")
        if self.root_expansion_multiplier != 2 or self.rollout_candidate_count != 5:
            raise ValueError("matched LATS WebShop reproduction expansion/rollout constants drifted")
        if self.success_reward != 1.0:
            raise ValueError("matched LATS WebShop success reward must be 1.0")
        if not self.requires_branchable_environment_state:
            raise ValueError("LATS requires recoverable environment state per search branch")


LATS_WEBSHOP_FIDELITY = LatsWebshopFidelity()


__all__ = ["LATS_WEBSHOP_FIDELITY", "LatsWebshopFidelity"]
