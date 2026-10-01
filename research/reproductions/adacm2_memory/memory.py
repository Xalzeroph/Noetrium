from __future__ import annotations

from dataclasses import dataclass
from research.reproductions._support import canonical_digest
from .fidelity import AdaCM2PartitionInterpretation

@dataclass(frozen=True, slots=True)
class AdaCM2ReductionSpec:
    interpretation: AdaCM2PartitionInterpretation
    alpha: float = 0.1
    beta: float = 0.1
    split_rounding: str = "floor-min-one"
    reserve_rounding: str = "ceil-min-one"

    def __post_init__(self) -> None:
        if not isinstance(self.interpretation, AdaCM2PartitionInterpretation):
            raise TypeError("AdaCM2 interpretation must be AdaCM2PartitionInterpretation")
        for name, value in (("alpha", self.alpha), ("beta", self.beta)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 < float(value) < 1.0:
                raise ValueError(f"AdaCM2 {name} must be in (0, 1)")
        if self.split_rounding != "floor-min-one" or self.reserve_rounding != "ceil-min-one":
            raise ValueError("AdaCM2 reduction rounding drifted")

    @property
    def previous_fraction(self) -> float:
        if self.interpretation is AdaCM2PartitionInterpretation.EQ6_LITERAL:
            return float(self.alpha)
        if self.interpretation is AdaCM2PartitionInterpretation.EQ8_CONSISTENT:
            return 1.0 - float(self.alpha)
        raise TypeError("unknown AdaCM2 partition interpretation")

    @property
    def recent_fraction(self) -> float:
        return 1.0 - self.previous_fraction

    @property
    def operational_retention_factor(self) -> float:
        return self.recent_fraction + self.previous_fraction * float(self.beta)

    @property
    def stated_theoretical_retention_factor(self) -> float:
        return float(self.alpha) + (1.0 - float(self.alpha)) * float(self.beta)

    @property
    def spec_digest(self) -> str:
        return canonical_digest({
            "interpretation": self.interpretation.value,
            "alpha": float(self.alpha),
            "beta": float(self.beta),
            "split_rounding": self.split_rounding,
            "reserve_rounding": self.reserve_rounding,
            "operational_retention_factor": self.operational_retention_factor,
            "stated_theoretical_retention_factor": self.stated_theoretical_retention_factor,
        })

__all__ = ("AdaCM2ReductionSpec",)
