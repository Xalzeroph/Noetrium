from __future__ import annotations

from dataclasses import dataclass
import math

from noetrium_platform.research.provenance import MethodSourceLane, MethodSourceLaneKind
from .source import SOURCE_OFFICIAL_GENERATED_CODE_AND_TRAJECTORIES

MARS_PAPER_URI = "https://arxiv.org/abs/2602.02660"
MARS_GRADING_REPORT_BLOB_SHA1S = (
    "d0152d8a035c0fe2494a18a6592c51e3a45d4752",
    "f420c97204a17e873fc3606dc6416ad4a5b68d1b",
    "a4e2cd542bffb225659d83a80741df2158aa5389",
)


def _mean_sem_percent(counts: tuple[int, ...], denominator: int) -> tuple[float, float]:
    percentages = tuple(100.0 * count / denominator for count in counts)
    mean = sum(percentages) / len(percentages)
    variance = sum((value - mean) ** 2 for value in percentages) / (len(percentages) - 1)
    return mean, math.sqrt(variance) / math.sqrt(len(percentages))


@dataclass(frozen=True, slots=True)
class MarsArtifactFidelity:
    """Official artifact/result lane; the released repository is not executable MARS source."""

    source: MethodSourceLane = SOURCE_OFFICIAL_GENERATED_CODE_AND_TRAJECTORIES
    released_content_scope: str = "generated_code_and_trajectories"
    executable_mars_agent_source_available: bool = False
    model: str = "Gemini-3-Pro-Preview"
    run_count: int = 3
    task_count_per_run: int = 75
    valid_submission_counts: tuple[int, ...] = (74, 74, 74)
    all_medal_counts: tuple[int, ...] = (40, 42, 44)
    low_medal_counts: tuple[int, ...] = (16, 17, 16)
    medium_medal_counts: tuple[int, ...] = (18, 20, 22)
    high_medal_counts: tuple[int, ...] = (6, 5, 6)
    low_task_count: int = 22
    medium_task_count: int = 38
    high_task_count: int = 15
    runtime_hours: int = 24

    def __post_init__(self) -> None:
        if self.source.kind is not MethodSourceLaneKind.OFFICIAL_ARTIFACT:
            raise ValueError("MARS release must remain an official artifact lane")
        if self.executable_mars_agent_source_available:
            raise ValueError("MARS artifact release must not be promoted to executable method source")
        if self.released_content_scope != "generated_code_and_trajectories":
            raise ValueError("MARS official release scope drifted")
        if (self.run_count, self.task_count_per_run) != (3, 75):
            raise ValueError("MARS artifact run matrix drifted")
        if self.valid_submission_counts != (74, 74, 74):
            raise ValueError("MARS artifact valid-submission counts drifted")
        if self.low_task_count + self.medium_task_count + self.high_task_count != 75:
            raise ValueError("MLE-Bench complexity split sizes must sum to 75")

    @property
    def all_medal_mean_sem(self) -> tuple[float, float]:
        return _mean_sem_percent(self.all_medal_counts, self.task_count_per_run)

    @property
    def low_medal_mean_sem(self) -> tuple[float, float]:
        return _mean_sem_percent(self.low_medal_counts, self.low_task_count)

    @property
    def medium_medal_mean_sem(self) -> tuple[float, float]:
        return _mean_sem_percent(self.medium_medal_counts, self.medium_task_count)

    @property
    def high_medal_mean_sem(self) -> tuple[float, float]:
        return _mean_sem_percent(self.high_medal_counts, self.high_task_count)


MARS_ARTIFACT_FIDELITY = MarsArtifactFidelity()

__all__ = [
    "MARS_GRADING_REPORT_BLOB_SHA1S",
    "MARS_PAPER_URI",
    "MarsArtifactFidelity",
]
