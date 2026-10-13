from __future__ import annotations

from dataclasses import dataclass

from .source import (
    FLASH_VSTREAM_LLAVA_PRECURSOR_COMMIT,
    FLASH_VSTREAM_QWEN_ICCV_COMMIT,
)


@dataclass(frozen=True, slots=True)
class FlashVStreamReferenceFidelity:
    paper_uri: str = (
        "https://openaccess.thecvf.com/content/ICCV2025/html/"
        "Zhang_Flash-VStream_Efficient_Real-Time_Understanding_"
        "for_Long_Video_Streams_ICCV_2025_paper.html"
    )
    source_repository: str = "https://github.com/IVGSZ/Flash-VStream"
    qwen_iccv_commit: str = FLASH_VSTREAM_QWEN_ICCV_COMMIT
    llava_precursor_commit: str = FLASH_VSTREAM_LLAVA_PRECURSOR_COMMIT
    llava_is_historical_precursor: bool = True

    context_memory_enabled: bool = True
    augmentation_memory_enabled: bool = True
    feature_bank_retained_for_augmentation: bool = True
    augmentation_conditioned_on_context_memory: bool = True
    memory_aware_rope_enabled: bool = True

    temporal_config_length: int = 120
    temporal_effective_packed_slots: int = 60
    temporal_method: str = "kmeans_ordered"
    temporal_pool_size: int = 2
    temporal_pca_dim: int = 32

    spatial_config_length: int = 60
    spatial_effective_packed_slots: int = 30
    spatial_method: str = "klarge_retrieve"
    spatial_retrieval_metric: str = "euclidean"
    spatial_retrieval_uses_high_weight_context_centroids: bool = True
    spatial_retrieval_returns_full_resolution_features: bool = True

    composition_order: tuple[str, ...] = (
        "augmentation_memory",
        "context_memory",
    )

    llava_memory_terms: tuple[str, ...] = (
        "long_memory",
        "Turing_memory",
    )
    qwen_memory_terms: tuple[str, ...] = (
        "CSM",
        "DAM",
    )

    def __post_init__(self) -> None:
        for value in (
            self.qwen_iccv_commit,
            self.llava_precursor_commit,
        ):
            if len(value) != 40:
                raise ValueError("Flash-VStream source commit must be a git SHA")
        if not self.llava_is_historical_precursor:
            raise ValueError(
                "The 2024 LLaVA release must remain a historical precursor"
            )
        if not all((
            self.context_memory_enabled,
            self.augmentation_memory_enabled,
            self.feature_bank_retained_for_augmentation,
            self.augmentation_conditioned_on_context_memory,
            self.memory_aware_rope_enabled,
        )):
            raise ValueError("Flash-VStream core memory semantics drifted")
        if (
            self.temporal_config_length,
            self.temporal_effective_packed_slots,
            self.temporal_pool_size,
            self.temporal_pca_dim,
        ) != (120, 60, 2, 32):
            raise ValueError("Flash-VStream temporal defaults drifted")
        if self.temporal_method != "kmeans_ordered":
            raise ValueError("Flash-VStream temporal method drifted")
        if (
            self.spatial_config_length,
            self.spatial_effective_packed_slots,
        ) != (60, 30):
            raise ValueError("Flash-VStream spatial defaults drifted")
        if self.spatial_method != "klarge_retrieve":
            raise ValueError("Flash-VStream spatial method drifted")
        if self.spatial_retrieval_metric != "euclidean":
            raise ValueError("Flash-VStream retrieval metric drifted")
        if self.composition_order != (
            "augmentation_memory",
            "context_memory",
        ):
            raise ValueError("Flash-VStream memory composition order drifted")


FLASH_VSTREAM_REFERENCE_FIDELITY = FlashVStreamReferenceFidelity()

__all__ = [
    "FLASH_VSTREAM_REFERENCE_FIDELITY",
    "FlashVStreamReferenceFidelity",
]
