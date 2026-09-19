from __future__ import annotations

from dataclasses import dataclass

from .source import DRVIDEO_OFFICIAL_COMMIT


@dataclass(frozen=True, slots=True)
class DrVideoReferenceFidelity:
    paper_uri: str = (
        "https://openaccess.thecvf.com/content/CVPR2025/html/"
        "Ma_DrVideo_Document_Retrieval_Based_Long_Video_"
        "Understanding_CVPR_2025_paper.html"
    )
    venue: str = "CVPR 2025"
    source_commit: str = DRVIDEO_OFFICIAL_COMMIT

    video_document_conversion: bool = True
    text_space_semantic_retrieval: bool = True
    question_conditioned_augmentation: bool = True
    multi_stage_agent_loop: bool = True
    chain_of_thought_answering: bool = True

    paper_initial_top_k: int = 5
    official_code_initial_top_k: int = 20
    max_agent_rounds: int = 2
    augmentation_types: tuple[str, ...] = ("caption", "vqa")
    maximum_added_frames_per_round: int = 3

    egoschema_sampling_fps: float = 0.5
    moviechat_sampling_fps: float = 0.5
    videomme_sampling_fps: float = 0.2
    egoschema_captioner: str = "LaViLa"
    moviechat_captioner: str = "LLaVA-NeXT"
    videomme_captioner: str = "LLaVA-NeXT"
    egoschema_moviechat_agent: str = "gpt-4-1106-preview"
    videomme_agent: str = "DeepSeek-V2.5"

    egoschema_public_task_count: int = 500
    egoschema_reported_accuracy: float = 0.664
    moviechat_global_reported_accuracy: float = 0.931
    moviechat_breakpoint_reported_accuracy: float = 0.564
    videomme_long_without_subtitles_accuracy: float = 0.517
    videomme_long_with_subtitles_accuracy: float = 0.717

    ablation_full_accuracy: float = 0.626
    ablation_without_retrieval_accuracy: float = 0.594
    ablation_without_agent_loop_accuracy: float = 0.606
    ablation_without_cot_accuracy: float = 0.622

    def __post_init__(self) -> None:
        if self.paper_initial_top_k != 5:
            raise ValueError("DrVideo paper Top-K drifted")
        if self.official_code_initial_top_k != 20:
            raise ValueError("DrVideo official-release Top-K drifted")
        if self.max_agent_rounds != 2:
            raise ValueError("DrVideo agent-loop round count drifted")
        if self.augmentation_types != ("caption", "vqa"):
            raise ValueError("DrVideo augmentation types drifted")
        if not all(
            (
                self.video_document_conversion,
                self.text_space_semantic_retrieval,
                self.question_conditioned_augmentation,
                self.multi_stage_agent_loop,
                self.chain_of_thought_answering,
            )
        ):
            raise ValueError("DrVideo core pipeline semantics drifted")


DRVIDEO_REFERENCE_FIDELITY = DrVideoReferenceFidelity()


__all__ = ["DRVIDEO_REFERENCE_FIDELITY", "DrVideoReferenceFidelity"]
