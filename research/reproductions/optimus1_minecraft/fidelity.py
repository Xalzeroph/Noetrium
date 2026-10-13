from __future__ import annotations

from dataclasses import dataclass

from .source import OPTIMUS1_PAPER_ERA_COMMIT


@dataclass(frozen=True, slots=True)
class Optimus1ReferenceFidelity:
    paper_uri: str = (
        "https://proceedings.neurips.cc/paper_files/paper/2024/hash/"
        "5949a8750a110ce1f0631b1776c500a2-Abstract-Conference.html"
    )
    venue: str = "NeurIPS 2024"
    source_commit: str = OPTIMUS1_PAPER_ERA_COMMIT

    hybrid_multimodal_memory: bool = True
    hdkg_enabled: bool = True
    amep_enabled: bool = True
    knowledge_guided_planner: bool = True
    experience_driven_reflector: bool = True
    action_controller: str = "steve1"

    hdkg_source: str = "minecraft_recipe_dependency_graph"
    hdkg_retrieval: str = "goal_conditioned_subgraph_compile"
    amep_plan_memory: bool = True
    amep_reflection_memory: bool = True
    amep_replan_memory: bool = True
    amep_reflection_labels: tuple[str, ...] = (
        "done",
        "continue",
        "replan",
    )
    plan_retrieval: str = "fuzzy_similar_task_success_plan"
    reflection_retrieval: str = (
        "fuzzy_similar_task_and_environment_then_category_example"
    )
    reflection_is_multimodal: bool = True
    replan_uses_error_conditioned_experience: bool = True

    paper_long_horizon_task_count: int = 67
    official_release_config_task_count: int = 73
    paper_task_group_count: int = 7
    headline_groups: tuple[str, ...] = (
        "iron",
        "gold",
        "diamond",
        "redstone",
        "armor",
    )
    reported_metrics: tuple[str, ...] = (
        "success_rate",
        "average_steps",
        "average_time",
    )

    official_release_planner_model: str = "gpt-4o"
    official_release_environment: str = "MineRL-MCP-Reborn"
    official_release_controller_checkpoint: str = "steve1"

    def __post_init__(self) -> None:
        if len(self.source_commit) != 40:
            raise ValueError("Optimus-1 source commit must be a git SHA")
        if not all(
            (
                self.hybrid_multimodal_memory,
                self.hdkg_enabled,
                self.amep_enabled,
                self.knowledge_guided_planner,
                self.experience_driven_reflector,
            )
        ):
            raise ValueError("Optimus-1 core architecture semantics drifted")
        if self.amep_reflection_labels != ("done", "continue", "replan"):
            raise ValueError("Optimus-1 reflection label semantics drifted")
        if self.paper_long_horizon_task_count != 67:
            raise ValueError("Optimus-1 paper task count drifted")
        if self.official_release_config_task_count != 73:
            raise ValueError("Optimus-1 official config task count drifted")
        if self.paper_long_horizon_task_count == self.official_release_config_task_count:
            raise ValueError("Optimus-1 paper/release benchmark delta was lost")


OPTIMUS1_REFERENCE_FIDELITY = Optimus1ReferenceFidelity()


__all__ = ["OPTIMUS1_REFERENCE_FIDELITY", "Optimus1ReferenceFidelity"]
