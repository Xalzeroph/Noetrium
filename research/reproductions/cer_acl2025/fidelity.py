from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class CERFidelity:
    paper_uri: str = "https://aclanthology.org/2025.acl-long.694/"
    venue: str = "ACL"
    year: int = 2025
    benchmark_ids: tuple[str, ...] = ("visualwebarena", "webarena")
    phase_ids: tuple[str, ...] = ("retrieve_experience", "adapt_context", "act", "evaluate", "store_experience")
    def __post_init__(self) -> None:
        if self.year not in (2025, 2026):
            raise ValueError("recent-paper fidelity year drifted")
        if not self.benchmark_ids or not self.phase_ids:
            raise ValueError("recent-paper fidelity requires benchmarks and phases")
        if len(self.phase_ids) != len(set(self.phase_ids)):
            raise ValueError("recent-paper phase ids must be unique")

CER_FIDELITY = CERFidelity()
__all__ = ["CERFidelity", "CER_FIDELITY"]
