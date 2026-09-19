from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.research.provenance import MethodSourceLane
from .source import SOURCE_LATER_RELEASED_LATS_REPO



@dataclass(frozen=True, slots=True)
class LATSWebShopFidelity:
    """Released WebShop experiment semantics at the audited LATS source cut."""

    source: MethodSourceLane = SOURCE_LATER_RELEASED_LATS_REPO
    source_artifact: str = "webshop/lats.py"
    launcher_artifact: str = "webshop/lats.sh"
    environment: str = "webshop"
    think_prefix: str = "think["
    think_observation: str = "OK."
    success_reward: float = 1.0
    max_tree_depth: int = 15
    max_iterations: int = 30
    implementation_default_iterations: int = 50
    task_start_index: int = 0
    task_end_index: int = 50
    reference_model: str = "gpt-3.5-turbo"
    temperature: float = 1.0
    root_expansion_multiplier: int = 2
    rollout_candidate_count: int = 5
    value_evaluation_sample_count: int = 1
    uct_exploration_constant: float = 2.0
    reflection_failed_trajectory_limit_exclusive: int = 4
    unique_failed_trajectory_limit: int = 3
    child_environment_semantics: str = "restore_parent_branch_state_before_candidate_action"
    uses_uct_selection: bool = True
    uses_lm_value_function: bool = True
    uses_failed_trajectory_reflection: bool = True
    requires_branchable_environment_state: bool = True

    @property
    def max_depth(self) -> int:
        return self.max_tree_depth

    @property
    def task_count(self) -> int:
        return self.task_end_index - self.task_start_index

    def __post_init__(self) -> None:
        if self.environment != "webshop" or self.success_reward != 1.0:
            raise ValueError("LATS WebShop environment semantics drifted")
        if self.max_tree_depth != 15:
            raise ValueError("LATS WebShop tree-depth semantics drifted")
        if self.max_iterations != 30 or self.implementation_default_iterations != 50:
            raise ValueError("LATS must distinguish released 30-iteration invocation from 50-iteration function default")
        if (self.task_start_index, self.task_end_index) != (0, 50):
            raise ValueError("released LATS WebShop launcher evaluates task indices 0 through 49")
        if (self.reference_model, self.temperature) != ("gpt-3.5-turbo", 1.0):
            raise ValueError("released LATS WebShop model invocation drifted")
        if self.root_expansion_multiplier != 2 or self.rollout_candidate_count != 5:
            raise ValueError("matched LATS WebShop expansion/rollout constants drifted")
        if self.value_evaluation_sample_count != 1:
            raise ValueError("released LATS WebShop value evaluation sample count drifted")
        if self.uct_exploration_constant != 2.0:
            raise ValueError("LATS UCT exploration constant drifted")
        if (self.reflection_failed_trajectory_limit_exclusive, self.unique_failed_trajectory_limit) != (4, 3):
            raise ValueError("LATS reflection limits drifted")
        if self.child_environment_semantics != "restore_parent_branch_state_before_candidate_action":
            raise ValueError("LATS branch environment semantics drifted")
        if not self.requires_branchable_environment_state:
            raise ValueError("LATS requires recoverable environment state per search branch")


LATS_WEBSHOP_FIDELITY = LATSWebShopFidelity()
LatsWebshopFidelity = LATSWebShopFidelity


__all__ = [
    "LATS_WEBSHOP_FIDELITY",
    "LATSWebShopFidelity",
    "LatsWebshopFidelity",
]
