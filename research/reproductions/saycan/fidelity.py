from __future__ import annotations

from dataclasses import dataclass


SAYCAN_REPOSITORY = "google-research/google-research"
SAYCAN_PAPER_CODE_COMMIT = "8c56e5dfc49613a57b80d6cfa2c9d6605cc08d10"


@dataclass(frozen=True, slots=True)
class SayCanFidelity:
    repository: str = SAYCAN_REPOSITORY
    paper_code_commit: str = SAYCAN_PAPER_CODE_COMMIT
    paper_arxiv: str = "2204.01691"
    source_path: str = "saycan/SayCan-Robot-Pick-Place.ipynb"
    language_score_space: str = "log-score"
    language_score_transform: str = "exp"
    affordance_range: tuple[float, float] = (0.0, 1.0)
    combined_score_rule: str = "exp(llm_log_score) * affordance_score"
    normalize_before_selection: bool = True
    selection_rule: str = "argmax-first-in-option-order"
    normalization_rule: str = "clip(combined / max(combined), 0, 1)"
    termination_string: str = "done()"
    termination_affordance: float = 0.2
    demo_max_tasks: int = 5
    affordance_scores_frozen_during_planning: bool = True
    planning_precedes_skill_execution: bool = True
    skill_execution_is_external: bool = True

    def __post_init__(self) -> None:
        if len(self.paper_code_commit) != 40:
            raise ValueError("SayCan source cut must be a full git SHA")
        if self.language_score_space != "log-score" or self.language_score_transform != "exp":
            raise ValueError("SayCan language scoring semantics drifted")
        if self.affordance_range != (0.0, 1.0):
            raise ValueError("SayCan affordance range drifted")
        if self.combined_score_rule != "exp(llm_log_score) * affordance_score":
            raise ValueError("SayCan score composition drifted")
        if (
            not self.normalize_before_selection
            or self.selection_rule != "argmax-first-in-option-order"
            or self.normalization_rule
            != "clip(combined / max(combined), 0, 1)"
        ):
            raise ValueError("SayCan selection semantics drifted")
        if (
            self.termination_string != "done()"
            or self.termination_affordance != 0.2
            or self.demo_max_tasks != 5
        ):
            raise ValueError("SayCan released demo loop semantics drifted")
        if not (
            self.affordance_scores_frozen_during_planning
            and self.planning_precedes_skill_execution
        ):
            raise ValueError("SayCan released demo plan/execute ordering drifted")
        if not self.skill_execution_is_external:
            raise ValueError("SayCan planner must not own robot skill execution")


SAYCAN_FIDELITY = SayCanFidelity()


__all__ = [
    "SAYCAN_FIDELITY",
    "SAYCAN_PAPER_CODE_COMMIT",
    "SAYCAN_REPOSITORY",
    "SayCanFidelity",
]
