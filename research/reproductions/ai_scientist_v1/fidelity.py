from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


AI_SCIENTIST_V1_REPOSITORY = "SakanaAI/AI-Scientist"
AI_SCIENTIST_V1_SOURCE_COMMIT = "0eccd134221c5ebec3fe0d2d6e8f67bfdbb69978"


class AIScientistV1Stage(StrEnum):
    IDEA_GENERATION = "idea_generation"
    NOVELTY_CHECK = "novelty_check"
    PROJECT_FORK = "project_fork"
    EXPERIMENT = "experiment"
    PLOTTING = "plotting"
    WRITEUP = "writeup"
    REVIEW = "review"
    IMPROVEMENT = "improvement"


@dataclass(frozen=True, slots=True)
class AIScientistV1Fidelity:
    repository: str = AI_SCIENTIST_V1_REPOSITORY
    source_commit: str = AI_SCIENTIST_V1_SOURCE_COMMIT
    paper_arxiv: str = "2408.06292"
    launch_source: str = "launch_scientist.py"
    experiment_source: str = "ai_scientist/perform_experiments.py"
    writeup_source: str = "ai_scientist/perform_writeup.py"
    review_source: str = "ai_scientist/perform_review.py"
    idea_count_default: int = 50
    idea_reflections: int = 3
    baseline_run: int = 0
    max_experiment_runs: int = 5
    max_repair_iterations: int = 4
    experiment_timeout_seconds: int = 7200
    plotting_timeout_seconds: int = 600
    max_stderr_chars: int = 1500
    review_reflections: int = 5
    review_ensemble_size: int = 5
    writeup_format: str = "latex"
    template_dependent: bool = True
    novel_ideas_only: bool = True
    stage_order: tuple[AIScientistV1Stage, ...] = (
        AIScientistV1Stage.IDEA_GENERATION,
        AIScientistV1Stage.NOVELTY_CHECK,
        AIScientistV1Stage.PROJECT_FORK,
        AIScientistV1Stage.EXPERIMENT,
        AIScientistV1Stage.PLOTTING,
        AIScientistV1Stage.WRITEUP,
        AIScientistV1Stage.REVIEW,
    )

    def __post_init__(self) -> None:
        if len(self.source_commit) != 40:
            raise ValueError("AI Scientist v1 source commit must be a full git SHA")
        if (self.idea_count_default, self.idea_reflections) != (50, 3):
            raise ValueError("AI Scientist v1 ideation semantics drifted")
        if (self.baseline_run, self.max_experiment_runs, self.max_repair_iterations) != (0, 5, 4):
            raise ValueError("AI Scientist v1 experiment budget drifted")
        if (self.experiment_timeout_seconds, self.plotting_timeout_seconds, self.max_stderr_chars) != (
            7200,
            600,
            1500,
        ):
            raise ValueError("AI Scientist v1 execution limits drifted")
        if (self.review_reflections, self.review_ensemble_size) != (5, 5):
            raise ValueError("AI Scientist v1 review semantics drifted")
        if self.writeup_format != "latex" or not self.template_dependent or not self.novel_ideas_only:
            raise ValueError("AI Scientist v1 pipeline semantics drifted")


AI_SCIENTIST_V1_FIDELITY = AIScientistV1Fidelity()


__all__ = [
    "AI_SCIENTIST_V1_FIDELITY",
    "AI_SCIENTIST_V1_REPOSITORY",
    "AI_SCIENTIST_V1_SOURCE_COMMIT",
    "AIScientistV1Fidelity",
    "AIScientistV1Stage",
]
