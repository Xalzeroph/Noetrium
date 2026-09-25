from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorldMMReferenceFidelity:
    source_revision: str = (
        "initial-public-release:"
        "5a5f779026d51024746e7b3fab7959dd0beedcd7"
    )
    memory_types: tuple[str, ...] = (
        "episodic",
        "semantic",
        "visual",
    )
    episodic_granularities: tuple[str, ...] = (
        "30sec",
        "3min",
        "10min",
        "1h",
    )
    episodic_candidate_top_k: tuple[tuple[str, int], ...] = (
        ("30sec", 10),
        ("3min", 5),
        ("10min", 5),
        ("1h", 3),
    )
    episodic_public_top_k: int = 3
    episodic_inner_final_top_k_multiplier: int = 2
    semantic_public_top_k: int = 10
    semantic_inner_top_k_multiplier: int = 2
    semantic_retrieval: str = (
        "embedding-personalization-then-entity-ppr"
    )
    semantic_ppr_damping: float = 0.85
    semantic_triple_score: str = "subject-ppr-plus-object-ppr"
    visual_public_top_k: int = 3
    visual_clip_seconds: int = 30
    visual_frame_fps: float = 1.0
    visual_max_frames: int = 64
    visual_query_modes: tuple[str, ...] = (
        "cross-modal-similarity",
        "timestamp-range",
    )
    max_retrieval_rounds: int = 5
    max_reasoning_errors: int = 5
    selected_memories_per_round: int = 1
    duplicate_suppression_shared_across_rounds: bool = True
    final_answer_uses_accumulated_context: bool = True
    malformed_reasoning_json_defaults_to_answer: bool = True

    def __post_init__(self) -> None:
        if self.memory_types != ("episodic", "semantic", "visual"):
            raise ValueError("WorldMM memory type set drifted")
        if self.episodic_granularities != (
            "30sec",
            "3min",
            "10min",
            "1h",
        ):
            raise ValueError("WorldMM episodic granularities drifted")
        if self.episodic_candidate_top_k != (
            ("30sec", 10),
            ("3min", 5),
            ("10min", 5),
            ("1h", 3),
        ):
            raise ValueError("WorldMM episodic candidate budgets drifted")
        if (
            self.episodic_public_top_k,
            self.semantic_public_top_k,
            self.visual_public_top_k,
        ) != (3, 10, 3):
            raise ValueError("WorldMM retrieval top-k defaults drifted")
        if (
            self.episodic_inner_final_top_k_multiplier,
            self.semantic_inner_top_k_multiplier,
        ) != (2, 2):
            raise ValueError("WorldMM duplicate-filter over-retrieval drifted")
        if self.semantic_retrieval != (
            "embedding-personalization-then-entity-ppr"
        ):
            raise ValueError("WorldMM semantic retrieval algorithm drifted")
        if self.semantic_ppr_damping != 0.85:
            raise ValueError("WorldMM semantic PPR damping drifted")
        if (
            self.visual_clip_seconds,
            self.visual_frame_fps,
            self.visual_max_frames,
        ) != (30, 1.0, 64):
            raise ValueError("WorldMM visual retrieval defaults drifted")
        if (
            self.max_retrieval_rounds,
            self.max_reasoning_errors,
            self.selected_memories_per_round,
        ) != (5, 5, 1):
            raise ValueError("WorldMM reasoning-loop bounds drifted")
        if not all((
            self.duplicate_suppression_shared_across_rounds,
            self.final_answer_uses_accumulated_context,
            self.malformed_reasoning_json_defaults_to_answer,
        )):
            raise ValueError("WorldMM control-flow semantics drifted")


WORLDMM_REFERENCE_FIDELITY = WorldMMReferenceFidelity()


__all__ = [
    "WORLDMM_REFERENCE_FIDELITY",
    "WorldMMReferenceFidelity",
]
