from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class VIDEOARMFidelity:
    paper_uri: str = "https://openaccess.thecvf.com/content/CVPR2026/html/Yin_VideoARM_Agentic_Reasoning_over_Hierarchical_Memory_for_Long-Form_Video_Understanding_CVPR_2026_paper.html"
    venue: str = "CVPR"
    year: int = 2026
    benchmark_ids: tuple[str, ...] = ("egoschema",)
    phase_ids: tuple[str, ...] = ("observe", "think", "act", "memorize", "answer")
    def __post_init__(self) -> None:
        if self.year not in (2025, 2026):
            raise ValueError("recent-paper fidelity year drifted")
        if not self.benchmark_ids or not self.phase_ids:
            raise ValueError("recent-paper fidelity requires benchmarks and phases")
        if len(self.phase_ids) != len(set(self.phase_ids)):
            raise ValueError("recent-paper phase ids must be unique")

VIDEOARM_FIDELITY = VIDEOARMFidelity()
__all__ = ["VIDEOARMFidelity", "VIDEOARM_FIDELITY"]
