from __future__ import annotations

from dataclasses import dataclass

from .source import MALMM_AUDITED_COMMIT, MALMM_COMPATIBILITY_COMMIT


@dataclass(frozen=True, slots=True)
class MALMMReferenceFidelity:
    paper_uri: str = (
        "https://openaccess.thecvf.com/content/CVPR2024/html/"
        "He_MA-LMM_Memory-Augmented_Large_Multimodal_Model_for_"
        "Long-Term_Video_Understanding_CVPR_2024_paper.html"
    )
    source_repository: str = "https://github.com/boheumd/MA-LMM"
    audited_commit: str = MALMM_AUDITED_COMMIT
    compatibility_commit: str = MALMM_COMPATIBILITY_COMMIT

    online_frame_processing: bool = True
    visual_memory_bank: bool = True
    query_memory_bank: bool = True
    adjacent_cosine_compression: bool = True
    per_token_merge_selection: bool = True
    compression_size_weighted_average: bool = True
    query_memory_extends_attention_keys_values: bool = True
    visual_memory_includes_position_embedding: bool = True
    parameterized_memory_bank_length: bool = True
    vector_database_retrieval: bool = False

    default_memory_bank_length: int = 10
    long_video_memory_bank_length: int = 20
    caption_memory_bank_length: int = 40
    query_token_count: int = 32
    visual_embedding_width: int = 1408

    compression_source: str = "lavis/models/blip2_models/blip2.py"
    visual_bank_source: str = (
        "lavis/models/blip2_models/blip2_vicuna_instruct.py"
    )

    def __post_init__(self) -> None:
        for value in (self.audited_commit, self.compatibility_commit):
            if len(value) != 40:
                raise ValueError("MA-LMM source commit must be a git SHA")
        if not all((
            self.online_frame_processing,
            self.visual_memory_bank,
            self.query_memory_bank,
            self.adjacent_cosine_compression,
            self.per_token_merge_selection,
            self.compression_size_weighted_average,
            self.query_memory_extends_attention_keys_values,
            self.visual_memory_includes_position_embedding,
            self.parameterized_memory_bank_length,
        )):
            raise ValueError("MA-LMM core memory semantics drifted")
        if self.vector_database_retrieval:
            raise ValueError(
                "MA-LMM paper memory is online tensor memory, not vector RAG"
            )
        if (
            self.default_memory_bank_length,
            self.long_video_memory_bank_length,
            self.caption_memory_bank_length,
            self.query_token_count,
            self.visual_embedding_width,
        ) != (10, 20, 40, 32, 1408):
            raise ValueError("MA-LMM released configuration semantics drifted")


MALMM_REFERENCE_FIDELITY = MALMMReferenceFidelity()


__all__ = ["MALMM_REFERENCE_FIDELITY", "MALMMReferenceFidelity"]
