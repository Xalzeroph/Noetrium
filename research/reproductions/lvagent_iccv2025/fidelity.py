from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class LVAGENTFidelity:
    paper_uri: str = "https://openaccess.thecvf.com/content/ICCV2025/html/Chen_LVAgent_Long_Video_Understanding_by_Multi-Round_Dynamical_Collaboration_of_MLLM_ICCV_2025_paper.html"
    venue: str = "ICCV"
    year: int = 2025
    benchmark_ids: tuple[str, ...] = ("egoschema",)
    phase_ids: tuple[str, ...] = ("select_team", "perceive", "discuss", "reflect", "consensus")
    def __post_init__(self) -> None:
        if self.year not in (2025, 2026):
            raise ValueError("recent-paper fidelity year drifted")
        if not self.benchmark_ids or not self.phase_ids:
            raise ValueError("recent-paper fidelity requires benchmarks and phases")
        if len(self.phase_ids) != len(set(self.phase_ids)):
            raise ValueError("recent-paper phase ids must be unique")

LVAGENT_FIDELITY = LVAGENTFidelity()
__all__ = ["LVAGENTFidelity", "LVAGENT_FIDELITY"]
