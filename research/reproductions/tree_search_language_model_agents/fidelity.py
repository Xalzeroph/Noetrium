from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.research.provenance import MethodSourceLane
from .source import SOURCE_OFFICIAL_SEARCH_AGENTS_REPO


@dataclass(frozen=True, slots=True)
class TreeSearchVwaFidelity:
    source: MethodSourceLane = SOURCE_OFFICIAL_SEARCH_AGENTS_REPO
    launcher_path: str = "scripts/run_vwa_shopping_search.sh"
    runner_path: str = "run.py"
    benchmark: str = "VisualWebArena"
    site: str = "shopping"
    task_start_index: int = 0
    task_end_index_exclusive: int = 466
    task_count: int = 466
    agent_type: str = "search"
    search_algorithm: str = "vf"
    policy_model: str = "gpt-4o"
    value_model: str = "gpt-4o-2024-05-13"
    evaluation_captioner_model: str = "Salesforce/blip2-flan-t5-xl"
    temperature: float = 1.0
    top_p: float = 0.95
    max_steps: int = 5
    max_depth: int = 4
    branching_factor: int = 5
    value_function_budget: int = 20
    repeating_action_failure_threshold: int = 5
    viewport_height: int = 2048
    max_observation_length: int = 3840
    action_set_tag: str = "som"
    observation_type: str = "image_som"
    prompt_path: str = "agent/prompts/jsons/p_som_cot_id_actree_3s.json"
    environment_branch_strategy: str = "reset_and_replay_action_history"
    launcher_reset_batch_size: int = 5

    def __post_init__(self) -> None:
        if self.task_count != self.task_end_index_exclusive - self.task_start_index:
            raise ValueError("Tree Search task count must match the released launcher range")
        if self.max_depth < 0 or self.max_steps <= 0 or self.branching_factor <= 0:
            raise ValueError("Tree Search search limits must be positive")
        if self.value_function_budget <= 0:
            raise ValueError("Tree Search value-function budget must be positive")

    @property
    def lookahead_steps(self) -> int:
        return self.max_depth + 1


TREE_SEARCH_VWA_FIDELITY = TreeSearchVwaFidelity()


__all__ = ["TREE_SEARCH_VWA_FIDELITY", "TreeSearchVwaFidelity"]
