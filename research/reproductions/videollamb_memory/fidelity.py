from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VideoLLaMBReferenceFidelity:
    paper_uri: str = (
        "https://openaccess.thecvf.com/content/ICCV2025/html/"
        "Wang_VideoLLaMB_Long_Streaming_Video_Understanding_with_"
        "Recurrent_Memory_Bridges_ICCV_2025_paper.html"
    )
    venue: str = "ICCV 2025"
    source_repository: str = "https://github.com/bigai-nlco/VideoLLaMB"
    source_commit: str = "962837c5b310559de18b375eaee20561123bb54c"
    recurrent_memory_tokens: bool = True
    memory_bridge_layers: bool = True
    memory_cache_retrieval: bool = True
    scene_tiling: bool = True
    bridge_transformer_layers: int = 1
    training_frames: int = 16
    training_segments: int = 4
    demonstrated_max_frames: int = 320
    demonstrated_gpu: str = "NVIDIA A100"
    linear_gpu_memory_scaling: bool = True
    training_free_streaming_captioning: bool = True
    videoqa_improvement_points: float = 4.2
    egocentric_planning_improvement_points: float = 2.06

    def __post_init__(self) -> None:
        if not all(
            (
                self.recurrent_memory_tokens,
                self.memory_bridge_layers,
                self.memory_cache_retrieval,
                self.scene_tiling,
                self.linear_gpu_memory_scaling,
                self.training_free_streaming_captioning,
            )
        ):
            raise ValueError("VideoLLaMB core memory semantics drifted")
        if self.bridge_transformer_layers != 1:
            raise ValueError("VideoLLaMB bridge depth drifted")
        if self.training_frames != 16 or self.training_segments != 4:
            raise ValueError("VideoLLaMB training geometry drifted")
        if self.demonstrated_max_frames != 320:
            raise ValueError("VideoLLaMB demonstrated frame scale drifted")


VIDEOLLAMB_REFERENCE_FIDELITY = VideoLLaMBReferenceFidelity()


__all__ = ["VIDEOLLAMB_REFERENCE_FIDELITY", "VideoLLaMBReferenceFidelity"]
