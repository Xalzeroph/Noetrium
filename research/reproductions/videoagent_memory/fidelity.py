from __future__ import annotations

from dataclasses import dataclass

from .source import (
    VIDEOAGENT_AUDITED_COMMIT,
    VIDEOAGENT_MULTIPLE_CHOICE_EXAMPLE_COMMIT,
)


@dataclass(frozen=True, slots=True)
class VideoAgentReferenceFidelity:
    paper_uri: str = (
        "https://www.ecva.net/papers/eccv_2024/papers_ECCV/"
        "html/3241_ECCV_2024_paper.php"
    )
    source_repository: str = "https://github.com/YueFan1014/VideoAgent"
    audited_commit: str = VIDEOAGENT_AUDITED_COMMIT
    post_paper_multiple_choice_commit: str = (
        VIDEOAGENT_MULTIPLE_CHOICE_EXAMPLE_COMMIT
    )

    segment_seconds: int = 2
    tracking_fps: int = 15
    object_embedding_sample_count: int = 5
    segment_localization_top_k: int = 5
    segment_visual_score_weight: int = 18
    segment_textual_score_weight: int = 11
    vqa_neighbor_radius_segments: int = 1
    gpt4v_sampled_frames: int = 4

    temporal_memory: bool = True
    object_memory: bool = True
    reidentification_default: bool = True
    default_vqa_backend: str = "videollava"
    main_reasoner_model: str = "gpt-4"
    object_reasoner_model: str = "gpt-4"
    reasoner_temperature: float = 0.0
    langchain_version: str = "0.1.2"
    agent_executor_max_iterations: int = 15
    agent_executor_early_stopping_method: str = "force"
    agent_executor_forced_output: str = (
        "Agent stopped due to iteration limit or time limit."
    )
    textual_embedding_model: str = "text-embedding-3-large"
    visual_embedding_model: str = "viclip-l-internvid-10m-flt"
    object_clip_model: str = "ViT-B/32"
    object_dinov2_model: str = "dinov2_vitg14"

    main_tools: tuple[str, ...] = (
        "caption_retrieval",
        "segment_localization",
        "visual_question_answering",
        "object_memory_querying",
    )
    object_memory_tools: tuple[str, ...] = (
        "database_querying",
        "open_vocabulary_object_retrieval",
    )

    caption_declared_max_count: int = 15
    caption_implementation_enforces_declared_limit: bool = False
    reid_seed: int = 0
    reid_clip_weight: float = 0.15
    reid_dinov2_weight: float = 0.85
    reid_all_member_threshold: float = 0.5
    reid_any_member_threshold: float = 0.62
    reid_clip_logistic_center: float = 0.925
    reid_clip_logistic_slope: float = 20.0
    reid_coexistence_hard_constraint: bool = True

    preprocessing_artifacts: tuple[str, ...] = (
        "captions.json",
        "segment_textual_embedding.pkl",
        "segment_visual_embedding.pkl",
        "segment2id.json",
        "tracking.pkl",
        "reid.pkl",
        "tid2clip.pkl",
        "tid2dinov2.pkl",
        "uid2clip.pkl",
        "reid.mp4",
    )

    def __post_init__(self) -> None:
        for value in (
            self.audited_commit,
            self.post_paper_multiple_choice_commit,
        ):
            if len(value) != 40:
                raise ValueError("VideoAgent source commit must be a git SHA")
        if (
            self.segment_seconds,
            self.tracking_fps,
            self.object_embedding_sample_count,
            self.segment_localization_top_k,
            self.segment_visual_score_weight,
            self.segment_textual_score_weight,
            self.vqa_neighbor_radius_segments,
            self.gpt4v_sampled_frames,
        ) != (2, 15, 5, 5, 18, 11, 1, 4):
            raise ValueError("VideoAgent released runtime constants drifted")
        if not all((
            self.temporal_memory,
            self.object_memory,
            self.reidentification_default,
            self.reid_coexistence_hard_constraint,
        )):
            raise ValueError("VideoAgent core memory semantics drifted")
        if self.default_vqa_backend != "videollava":
            raise ValueError("VideoAgent default VQA backend drifted")
        if (
            self.main_reasoner_model,
            self.object_reasoner_model,
            self.reasoner_temperature,
            self.langchain_version,
            self.agent_executor_max_iterations,
            self.agent_executor_early_stopping_method,
            self.agent_executor_forced_output,
        ) != (
            "gpt-4",
            "gpt-4",
            0.0,
            "0.1.2",
            15,
            "force",
            "Agent stopped due to iteration limit or time limit.",
        ):
            raise ValueError("VideoAgent paper-era reasoner semantics drifted")
        if self.main_tools != (
            "caption_retrieval",
            "segment_localization",
            "visual_question_answering",
            "object_memory_querying",
        ):
            raise ValueError("VideoAgent top-level tool set drifted")
        if self.object_memory_tools != (
            "database_querying",
            "open_vocabulary_object_retrieval",
        ):
            raise ValueError("VideoAgent object-memory tool set drifted")
        if self.caption_implementation_enforces_declared_limit:
            raise ValueError(
                "VideoAgent source describes a 15-caption tool limit but "
                "the implementation does not enforce it"
            )
        if (
            self.reid_seed,
            self.reid_clip_weight,
            self.reid_dinov2_weight,
            self.reid_all_member_threshold,
            self.reid_any_member_threshold,
            self.reid_clip_logistic_center,
            self.reid_clip_logistic_slope,
        ) != (0, 0.15, 0.85, 0.5, 0.62, 0.925, 20.0):
            raise ValueError("VideoAgent ReID semantics drifted")


VIDEOAGENT_REFERENCE_FIDELITY = VideoAgentReferenceFidelity()

__all__ = [
    "VIDEOAGENT_REFERENCE_FIDELITY",
    "VideoAgentReferenceFidelity",
]
