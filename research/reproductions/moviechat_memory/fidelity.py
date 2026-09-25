from __future__ import annotations

from dataclasses import dataclass

from .source import (
    MOVIECHAT_AUDITED_COMMIT,
    MOVIECHAT_INITIAL_RELEASE_COMMIT,
)


@dataclass(frozen=True, slots=True)
class MovieChatReferenceFidelity:
    audited_commit: str = MOVIECHAT_AUDITED_COMMIT
    initial_release_commit: str = MOVIECHAT_INITIAL_RELEASE_COMMIT

    short_memory_length: int = 18
    short_memory_merge: int = 2
    long_memory_length: int = 256
    position_base: int = 16
    position_capacity: int = 256

    fragments_per_video: int = 128
    frames_per_fragment: int = 8
    evaluation_seed: int = 42
    generation_num_beams: int = 1
    generation_temperature: float = 1.0
    generation_max_new_tokens: int = 300
    generation_max_context_length: int = 2000
    qa_evaluator_model: str = "claude-instant-1"
    qa_evaluator_consistency_threshold: float = 2.9
    global_questions_per_video: int = 3
    breakpoint_questions_per_video: int = 10

    short_memory_fifo: bool = True
    temp_short_snapshot_before_merge: bool = True
    short_similarity: str = "mean_pairwise_token_dot_product"
    short_pair_selection: str = "maximum_similarity"
    short_merge: str = "unweighted_arithmetic_mean"
    compressed_short_appended_to_long: bool = True
    short_cleared_after_fragment: bool = True

    direct_long_similarity: str = "scipy_cosine_distance"
    direct_long_pair_selection: str = "maximum_distance"
    direct_long_merge: str = "unweighted_arithmetic_mean"

    global_mode_uses_long_only: bool = True
    breakpoint_uses_long_temp_short_current: bool = True
    breakpoint_eviction_order: tuple[str, ...] = (
        "temp_short_oldest",
        "long_oldest",
    )
    moviechat_plus_backported: bool = False

    paper_consolidation_intent: str = (
        "top-1 adjacent cosine-similarity pair with weighted consolidation"
    )
    executable_long_memory_divergence: str = (
        "paper-era source imports scipy.spatial.distance.cosine and takes max, "
        "therefore the direct LTM path selects maximum cosine distance"
    )

    def __post_init__(self) -> None:
        if len(self.audited_commit) != 40 or len(self.initial_release_commit) != 40:
            raise ValueError("MovieChat source commits must be git SHAs")
        if (
            self.short_memory_length,
            self.short_memory_merge,
            self.long_memory_length,
            self.position_base,
            self.position_capacity,
        ) != (18, 2, 256, 16, 256):
            raise ValueError("MovieChat released memory capacities drifted")
        if self.position_capacity != self.position_base * self.position_base:
            raise ValueError("MovieChat extended position capacity drifted")
        if (
            self.fragments_per_video,
            self.frames_per_fragment,
            self.evaluation_seed,
            self.generation_num_beams,
            self.generation_max_new_tokens,
            self.generation_max_context_length,
            self.global_questions_per_video,
            self.breakpoint_questions_per_video,
        ) != (128, 8, 42, 1, 300, 2000, 3, 10):
            raise ValueError("MovieChat released evaluation protocol drifted")
        if self.generation_temperature != 1.0:
            raise ValueError("MovieChat generation temperature drifted")
        if self.qa_evaluator_model != "claude-instant-1":
            raise ValueError("MovieChat paper-era QA evaluator drifted")
        if self.qa_evaluator_consistency_threshold != 2.9:
            raise ValueError("MovieChat evaluator consistency threshold drifted")
        if not all((
            self.short_memory_fifo,
            self.temp_short_snapshot_before_merge,
            self.compressed_short_appended_to_long,
            self.short_cleared_after_fragment,
            self.global_mode_uses_long_only,
            self.breakpoint_uses_long_temp_short_current,
        )):
            raise ValueError("MovieChat memory control semantics drifted")
        if self.moviechat_plus_backported:
            raise ValueError("MovieChat+ must not be backported into MovieChat")
        if self.breakpoint_eviction_order != (
            "temp_short_oldest",
            "long_oldest",
        ):
            raise ValueError("MovieChat breakpoint eviction order drifted")


MOVIECHAT_REFERENCE_FIDELITY = MovieChatReferenceFidelity()


__all__ = [
    "MOVIECHAT_REFERENCE_FIDELITY",
    "MovieChatReferenceFidelity",
]
