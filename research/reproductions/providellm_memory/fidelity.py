from __future__ import annotations

from dataclasses import dataclass

from .source import PROVIDELLM_PAPER_ERA_COMMIT


@dataclass(frozen=True, slots=True)
class ProVideLLMReferenceFidelity:
    paper_uri: str = (
        "https://openaccess.thecvf.com/content/ICCV2025/html/"
        "Chatterjee_Streaming_VideoLLMs_for_Real-Time_Procedural_"
        "Video_Understanding_ICCV_2025_paper.html"
    )
    venue: str = "ICCV 2025"
    source_commit: str = PROVIDELLM_PAPER_ERA_COMMIT

    long_term_token_type: str = "verbalized_text"
    short_term_token_type: str = "detr_qformer_visual"
    cache_type: str = "multimodal_interleaved_fifo"
    single_entry_point: bool = True
    separate_short_long_exits: bool = True
    long_term_marker: str = "<L>"
    duplicate_suppression_window: str = "tau_frames"

    typical_short_term_min_seconds: int = 8
    typical_short_term_max_seconds: int = 16
    runtime_short_term_span_seconds: int = 16
    runtime_long_term_span_seconds: int = 128

    one_hour_verbalized_token_average: int = 630
    reported_token_reduction_factor: float = 22.0
    reported_per_frame_fps: float = 10.0
    reported_streaming_dialogue_fps: float = 24.6
    reported_gpu_memory_gb: float = 2.0

    official_streaming_interleave_code_released: bool = False
    official_detr_qformer_code_released: bool = True

    def __post_init__(self) -> None:
        if self.cache_type != "multimodal_interleaved_fifo":
            raise ValueError("ProVideLLM cache type drifted")
        if not self.single_entry_point or not self.separate_short_long_exits:
            raise ValueError("ProVideLLM interleaved-cache topology drifted")
        if self.long_term_marker != "<L>":
            raise ValueError("ProVideLLM long-term marker drifted")
        if (
            self.typical_short_term_min_seconds != 8
            or self.typical_short_term_max_seconds != 16
        ):
            raise ValueError("ProVideLLM short-term span drifted")
        if (
            self.runtime_short_term_span_seconds != 16
            or self.runtime_long_term_span_seconds != 128
        ):
            raise ValueError("ProVideLLM runtime-analysis span drifted")
        if self.reported_token_reduction_factor != 22.0:
            raise ValueError("ProVideLLM reported token compression drifted")
        if self.official_streaming_interleave_code_released:
            raise ValueError(
                "ProVideLLM official release does not expose streaming "
                "verbalize/interleave code"
            )


PROVIDELLM_REFERENCE_FIDELITY = ProVideLLMReferenceFidelity()


__all__ = [
    "PROVIDELLM_REFERENCE_FIDELITY",
    "ProVideLLMReferenceFidelity",
]
