from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.research.provenance import MethodSourceLane, MethodSourceLaneKind
from .source import SOURCE_PAPER_ERA_LITS_RELEASE


@dataclass(frozen=True, slots=True)
class LitsMath500ReleaseFidelity:
    """Paper-era executable LiTS MATH500 MCTS lane."""

    source: MethodSourceLane = SOURCE_PAPER_ERA_LITS_RELEASE
    benchmark_loader_artifact: str = "demos/lits_benchmark/math_qa.py"
    benchmark_dataset: str = "xinzhel/math500-float"
    benchmark_split: str = "test"
    search_algorithm: str = "mcts"
    policy_component: str = "concat"
    transition_component: str = "concat"
    reward_component: str = "generative"
    search_iterations: int = 50
    candidate_actions: int = 3
    max_steps: int = 10
    model_binding_semantics: str = "policy_and_reward_roles_are_explicit_but_concrete_model_is_user_bound"
    core_component_contracts: tuple[str, ...] = ("Policy", "Transition", "RewardModel")
    supported_search_algorithms: tuple[str, ...] = ("mcts", "bfs")
    task_type: str = "language_grounded"

    def __post_init__(self) -> None:
        if self.source.kind is not MethodSourceLaneKind.OFFICIAL_EXECUTABLE:
            raise ValueError("LiTS submission-day source must remain an official executable lane")
        if self.source is not SOURCE_PAPER_ERA_LITS_RELEASE:
            raise ValueError("LiTS source lane identity drifted")
        if self.benchmark_loader_artifact not in self.source.artifacts:
            raise ValueError("LiTS benchmark loader must be covered by the source lane")
        if self.benchmark_dataset != "xinzhel/math500-float" or self.benchmark_split != "test":
            raise ValueError("LiTS MATH500 loader identity drifted")
        if (self.search_algorithm, self.policy_component, self.transition_component, self.reward_component) != (
            "mcts",
            "concat",
            "concat",
            "generative",
        ):
            raise ValueError("LiTS released MATH500 component composition drifted")
        if (self.search_iterations, self.candidate_actions, self.max_steps) != (50, 3, 10):
            raise ValueError("LiTS released MATH500 MCTS budget drifted")
        if self.core_component_contracts != ("Policy", "Transition", "RewardModel"):
            raise ValueError("LiTS component ABI drifted")


LITS_MATH500_RELEASE_FIDELITY = LitsMath500ReleaseFidelity()

__all__ = [
    "LITS_MATH500_RELEASE_FIDELITY",
    "LitsMath500ReleaseFidelity",
]
