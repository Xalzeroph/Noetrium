from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReWindReferenceFidelity:
    """Camera-ready ReWind long-video memory semantics."""

    source_revision: str = "cvpr-2025-camera-ready"
    architecture_stages: tuple[str, str] = (
        "read-perceive-write",
        "dynamic-frame-selection",
    )
    sampling_fps: int = 1
    vision_encoder: str = "EVA-02-ViT-G/14"
    llm: str = "LLaMA-2-7B"
    perceiver_layers: int = 8
    read_query_count: int = 32
    perceiver_query_count: int = 32
    write_query_count: int = 2
    memory_tokens_per_frame: int = 2
    dfs_instruction_selection_count: int = 64
    dfs_final_frame_count: int = 8
    dfs_selected_frame_tokens: int = 32
    dfs_clustering: str = "DPC-KNN"
    memory_order: str = "temporal"
    feature_buffer_retains_original_visual_features: bool = True
    dfs_runs_after_full_video_memory: bool = True
    llm_input_order: tuple[str, ...] = (
        "memory",
        "separator",
        "selected_high_resolution_frames",
        "instruction",
    )
    pretraining_pairs: int = 100_000
    pretraining_steps: int = 10_000
    pretraining_batch_size: int = 64
    pretraining_learning_rate: float = 1e-4
    pretraining_warmup_steps: int = 500
    instruction_tuning_steps: int = 100_000
    instruction_tuning_batch_size: int = 64
    instruction_tuning_learning_rate: float = 5e-5
    instruction_tuning_warmup_steps: int = 2_000
    lora_rank: int = 64
    lora_alpha: int = 32
    input_resolution: tuple[int, int] = (224, 224)

    def __post_init__(self) -> None:
        if self.architecture_stages != (
            "read-perceive-write",
            "dynamic-frame-selection",
        ):
            raise ValueError("ReWind stage order drifted")
        if self.sampling_fps != 1:
            raise ValueError("ReWind sampling rate drifted")
        if (
            self.perceiver_layers,
            self.read_query_count,
            self.perceiver_query_count,
            self.write_query_count,
        ) != (8, 32, 32, 2):
            raise ValueError("ReWind query/perceiver configuration drifted")
        if self.memory_tokens_per_frame != self.write_query_count:
            raise ValueError(
                "ReWind memory tokens per frame must equal write queries"
            )
        if (
            self.dfs_instruction_selection_count,
            self.dfs_final_frame_count,
            self.dfs_selected_frame_tokens,
        ) != (64, 8, 32):
            raise ValueError("ReWind DFS configuration drifted")
        if self.dfs_clustering != "DPC-KNN":
            raise ValueError("ReWind DFS clustering drifted")
        if not all((
            self.feature_buffer_retains_original_visual_features,
            self.dfs_runs_after_full_video_memory,
        )):
            raise ValueError("ReWind buffer/selection semantics drifted")
        if self.llm_input_order != (
            "memory",
            "separator",
            "selected_high_resolution_frames",
            "instruction",
        ):
            raise ValueError("ReWind LLM input ordering drifted")


REWIND_REFERENCE_FIDELITY = ReWindReferenceFidelity()


__all__ = [
    "REWIND_REFERENCE_FIDELITY",
    "ReWindReferenceFidelity",
]
