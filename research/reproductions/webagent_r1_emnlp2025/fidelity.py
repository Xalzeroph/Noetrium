from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class WEBAGENT_R1Fidelity:
    paper_uri: str = "https://aclanthology.org/2025.emnlp-main.401/"
    venue: str = "EMNLP"
    year: int = 2025
    benchmark_ids: tuple[str, ...] = ("webarena",)
    phase_ids: tuple[str, ...] = ("warmup", "rollout", "reward", "update", "test_scale")
    def __post_init__(self) -> None:
        if self.year not in (2025, 2026):
            raise ValueError("recent-paper fidelity year drifted")
        if not self.benchmark_ids or not self.phase_ids:
            raise ValueError("recent-paper fidelity requires benchmarks and phases")
        if len(self.phase_ids) != len(set(self.phase_ids)):
            raise ValueError("recent-paper phase ids must be unique")

WEBAGENT_R1_FIDELITY = WEBAGENT_R1Fidelity()
__all__ = ["WEBAGENT_R1Fidelity", "WEBAGENT_R1_FIDELITY"]
