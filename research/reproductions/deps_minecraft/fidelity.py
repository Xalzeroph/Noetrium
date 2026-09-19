from __future__ import annotations

from dataclasses import dataclass

from .source import DEPS_RELEASE_COMMIT, DEPS_REPLAN_SEMANTICS_COMMIT


@dataclass(frozen=True, slots=True)
class DEPSMinecraftFidelity:
    paper_uri: str = (
        "https://proceedings.neurips.cc/paper_files/paper/2023/hash/"
        "6b8dfb8c0c12e6fafc6c256cb08a5ca7-Abstract-Conference.html"
    )
    source_repository: str = "https://github.com/CraftJarvis/MC-Planner"
    audited_commit: str = DEPS_RELEASE_COMMIT
    replan_semantics_commit: str = DEPS_REPLAN_SEMANTICS_COMMIT

    describe_enabled: bool = True
    explain_enabled: bool = True
    replan_enabled: bool = True
    learned_goal_selector: bool = True
    selector_release_complete: bool = False

    planner_model: str = "code-davinci-002"
    planner_temperature: float = 0.7
    planner_max_tokens: int = 1024
    parser_model: str = "text-davinci-003"
    parser_temperature: float = 0.0
    parser_max_tokens: int = 256
    parser_prompt_tail_characters: int = 4000
    model_query_retry_limit: int = 10

    craft_replan_step_threshold: int = 150
    smelt_replan_step_threshold: int = 200
    replan_round_limit: int = 12
    mine_replans_on_unsatisfied_precondition: bool = True
    success_requires_goal_steps_gt: int = 1

    failure_feedback_order: tuple[str, ...] = (
        "failed_step_description",
        "inventory_description",
        "failure_explanation",
        "replan_request",
    )
    fallback_goal_name: str = "mine_log"
    fallback_goal_type: str = "mine"
    fallback_goal_object: tuple[tuple[str, int], ...] = (("log", 1),)

    def __post_init__(self) -> None:
        for value in (self.audited_commit, self.replan_semantics_commit):
            if len(value) != 40:
                raise ValueError("DEPS source commit must be a git SHA")
        if not all((self.describe_enabled, self.explain_enabled, self.replan_enabled)):
            raise ValueError("DEPS interactive replanning semantics drifted")
        if not self.learned_goal_selector:
            raise ValueError("DEPS must preserve the learned goal selector")
        if self.selector_release_complete:
            raise ValueError(
                "official selector.py is an abstract shell and must not be "
                "represented as a complete released selector"
            )
        if (
            self.craft_replan_step_threshold,
            self.smelt_replan_step_threshold,
            self.replan_round_limit,
        ) != (150, 200, 12):
            raise ValueError("DEPS paper-release control bounds drifted")
        if self.failure_feedback_order != (
            "failed_step_description",
            "inventory_description",
            "failure_explanation",
            "replan_request",
        ):
            raise ValueError("DEPS failure feedback order drifted")
        if self.fallback_goal_name != "mine_log" or self.fallback_goal_type != "mine":
            raise ValueError("DEPS fallback goal drifted")


DEPS_MINECRAFT_FIDELITY = DEPSMinecraftFidelity()

__all__ = ["DEPS_MINECRAFT_FIDELITY", "DEPSMinecraftFidelity"]
