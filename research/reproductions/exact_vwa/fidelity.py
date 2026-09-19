from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.research.provenance import MethodSourceLane, MethodSourceLaneKind
from .source import SOURCE_LATER_RELEASED_EXACT_VWA



@dataclass(frozen=True, slots=True)
class ExactVwaFidelity:
    source: MethodSourceLane = SOURCE_LATER_RELEASED_EXACT_VWA
    source_branch: str = "vwa"
    launcher_artifact: str = "shells/classifieds/rmcts_mad_som.sh"
    benchmark_site: str = "classifieds"
    benchmark_config_dir: str = "configs/visualwebarena/test_classifieds_v2"
    task_count: int = 234
    agent_type: str = "rmcts_mad"
    policy_model: str = "gpt-4o"
    value_model: str = "gpt-4o"
    reflective_language_model: str = "gpt-4o"
    embedding_model: str = "text-embedding-3-small"
    max_depth: int = 4
    lookahead_steps: int = 5
    max_environment_steps: int = 5
    branching_factor: int = 5
    value_function_budget: int = 20
    time_budget_minutes_per_step: float = 5.0
    prompt_constructor_type: str = "ReinforcedPolicyPConstructor"
    max_reflections_per_task: int = 3
    reflection_threshold: float = 0.5
    puct: float = 1.0
    value_function_method: str = "ReinforcedDebateValueFunction"
    value_max_reflections_per_task: int = 1
    value_reflection_threshold: float = 0.5
    top_p: float = 0.95
    temperature: float = 1.0
    observation_type: str = "image_som"
    action_set_tag: str = "som"
    max_observation_length: int = 3840
    released_parallel_workers: int = 2
    tasks_per_script: int = 2
    tasks_per_environment_reset: int = 8
    environment_branch_strategy: str = "reset_and_replay_action_history"

    def __post_init__(self) -> None:
        if (self.source_branch, self.benchmark_site, self.task_count) != ("vwa", "classifieds", 234):
            raise ValueError("ExACT VWA classifieds released lane drifted")
        if (self.policy_model, self.value_model, self.reflective_language_model) != ("gpt-4o", "gpt-4o", "gpt-4o"):
            raise ValueError("ExACT GPT-4o model-role semantics drifted")
        if self.embedding_model != "text-embedding-3-small":
            raise ValueError("ExACT embedding model role drifted")
        if (self.max_depth, self.lookahead_steps, self.max_environment_steps) != (4, 5, 5):
            raise ValueError("ExACT R-MCTS depth/step semantics drifted")
        if (self.branching_factor, self.value_function_budget, self.time_budget_minutes_per_step) != (5, 20, 5.0):
            raise ValueError("ExACT R-MCTS search budget drifted")
        if (self.max_reflections_per_task, self.reflection_threshold, self.puct) != (3, 0.5, 1.0):
            raise ValueError("ExACT policy reflection/PUCT settings drifted")
        if (self.value_max_reflections_per_task, self.value_reflection_threshold) != (1, 0.5):
            raise ValueError("ExACT value reflection settings drifted")
        if (self.released_parallel_workers, self.tasks_per_script, self.tasks_per_environment_reset) != (2, 2, 8):
            raise ValueError("ExACT released parallel/reset orchestration drifted")
        if self.environment_branch_strategy != "reset_and_replay_action_history":
            raise ValueError("ExACT released environment reconstruction strategy drifted")


EXACT_VWA_FIDELITY = ExactVwaFidelity()

__all__ = ["EXACT_VWA_FIDELITY", "ExactVwaFidelity"]
