from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class WATCH_AND_LEARNFidelity:
    paper_uri: str = "https://openaccess.thecvf.com/content/CVPR2026/html/Song_Watch_and_Learn_Learning_to_Use_Computers_from_Online_Videos_CVPR_2026_paper.html"
    venue: str = "CVPR"
    year: int = 2026
    benchmark_ids: tuple[str, ...] = ("osworld",)
    phase_ids: tuple[str, ...] = ("retrieve_video", "inverse_dynamics", "label_trajectory", "condition_policy", "execute")
    def __post_init__(self) -> None:
        if self.year not in (2025, 2026):
            raise ValueError("recent-paper fidelity year drifted")
        if not self.benchmark_ids or not self.phase_ids:
            raise ValueError("recent-paper fidelity requires benchmarks and phases")
        if len(self.phase_ids) != len(set(self.phase_ids)):
            raise ValueError("recent-paper phase ids must be unique")

WATCH_AND_LEARN_FIDELITY = WATCH_AND_LEARNFidelity()
__all__ = ["WATCH_AND_LEARNFidelity", "WATCH_AND_LEARN_FIDELITY"]
