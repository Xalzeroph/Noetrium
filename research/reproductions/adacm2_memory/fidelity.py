from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AdaCM2PartitionInterpretation(StrEnum):
    """Two mutually inconsistent cache-ratio claims in the camera-ready paper."""

    EQ6_LITERAL = "eq6_literal"
    EQ8_CONSISTENT = "eq8_consistent"


@dataclass(frozen=True, slots=True)
class AdaCM2ReferenceFidelity:
    source_revision: str = "cvpr-2025-camera-ready"
    visual_encoder: str = "EVA-CLIP-ViT-G/14"
    qformer_initialization: str = "InstructBLIP"
    llm: str = "Vicuna-7B-v1.1"
    frame_sampling_fps: int = 10
    visual_encoder_frozen: bool = True
    llm_frozen: bool = True
    qformer_trainable: bool = True
    cross_modal_score_reduction: str = "sum-over-query-text-rows"
    reduction_scope: str = "layer-wise-kv-cache"
    previous_selection: str = "top-beta-cross-modal-attention"
    recent_cache_retained_fully: bool = True
    alpha: float = 0.1
    beta: float = 0.1
    stated_theoretical_retention_formula: str = "alpha+(1-alpha)*beta"
    stated_asymptotic_cache_bound: str = "P*r/(1-r)"
    eq6_recent_previous_ratio: str = "(1-alpha)/alpha"
    eq6_and_eq8_are_jointly_inconsistent: bool = True
    lvu_tasks: tuple[str, ...] = (
        "relationship",
        "speaking_style",
        "scene",
        "director",
        "genre",
        "writer",
        "release_year",
    )

    def __post_init__(self) -> None:
        if self.frame_sampling_fps != 10:
            raise ValueError("AdaCM2 frame sampling rate drifted")
        if not all((
            self.visual_encoder_frozen,
            self.llm_frozen,
            self.qformer_trainable,
            self.recent_cache_retained_fully,
            self.eq6_and_eq8_are_jointly_inconsistent,
        )):
            raise ValueError("AdaCM2 frozen/trainable or paper-quirk semantics drifted")
        if (self.alpha, self.beta) != (0.1, 0.1):
            raise ValueError("AdaCM2 paper hyperparameters drifted")
        if self.cross_modal_score_reduction != "sum-over-query-text-rows":
            raise ValueError("AdaCM2 cross-modal score semantics drifted")
        if self.reduction_scope != "layer-wise-kv-cache":
            raise ValueError("AdaCM2 reduction scope drifted")
        if self.previous_selection != "top-beta-cross-modal-attention":
            raise ValueError("AdaCM2 previous-cache selection drifted")

    @property
    def eq8_retention_factor(self) -> float:
        return self.alpha + (1.0 - self.alpha) * self.beta

    @property
    def eq6_literal_operational_retention_factor(self) -> float:
        # Eq.6 makes previous cache alpha of the pre-reduction cache and
        # recent cache (1-alpha). Retaining beta of previous therefore gives
        # (1-alpha) + alpha*beta, not the factor printed in Eq.8.
        return (1.0 - self.alpha) + self.alpha * self.beta

    def operational_retention_factor(
        self,
        interpretation: AdaCM2PartitionInterpretation,
    ) -> float:
        if interpretation is AdaCM2PartitionInterpretation.EQ6_LITERAL:
            return self.eq6_literal_operational_retention_factor
        if interpretation is AdaCM2PartitionInterpretation.EQ8_CONSISTENT:
            return self.eq8_retention_factor
        raise TypeError("unknown AdaCM2 partition interpretation")


ADACM2_REFERENCE_FIDELITY = AdaCM2ReferenceFidelity()


__all__ = [
    "ADACM2_REFERENCE_FIDELITY",
    "AdaCM2PartitionInterpretation",
    "AdaCM2ReferenceFidelity",
]
