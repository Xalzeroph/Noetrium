from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class EMBODIED_VIDEOAGENTFidelity:
    paper_uri: str = "https://openaccess.thecvf.com/content/ICCV2025/html/Fan_Embodied_VideoAgent_Persistent_Memory_from_Egocentric_Videos_and_Embodied_Sensors_ICCV_2025_paper.html"
    venue: str = "ICCV"
    year: int = 2025
    benchmark_ids: tuple[str, ...] = ("open-eqa", "envqa", "ego4d-vq3d")
    phase_ids: tuple[str, ...] = ("ingest", "associate", "update", "retrieve", "respond")
    def __post_init__(self) -> None:
        if self.year not in (2025, 2026):
            raise ValueError("recent-paper fidelity year drifted")
        if not self.benchmark_ids or not self.phase_ids:
            raise ValueError("recent-paper fidelity requires benchmarks and phases")
        if len(self.phase_ids) != len(set(self.phase_ids)):
            raise ValueError("recent-paper phase ids must be unique")

EMBODIED_VIDEOAGENT_FIDELITY = EMBODIED_VIDEOAGENTFidelity()
__all__ = ["EMBODIED_VIDEOAGENTFidelity", "EMBODIED_VIDEOAGENT_FIDELITY"]
