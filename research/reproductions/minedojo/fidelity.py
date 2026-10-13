from __future__ import annotations

from dataclasses import dataclass

from .source import (
    MINECLIP_AUDITED_COMMIT,
    MINEDOJO_AUDITED_COMMIT,
)


MINEDOJO_TASK_CATEGORIES = (
    "programmatic",
    "creative",
    "playthrough",
)

MINEDOJO_PROGRAMMATIC_FAMILIES = (
    "survival",
    "harvest",
    "tech_tree",
    "combat",
)

MINECLIP_VARIANTS = (
    "attn",
    "avg",
)


@dataclass(frozen=True, slots=True)
class MineDojoReferenceFidelity:
    """Paper/release semantics for the MineDojo + MineCLIP foundational lane."""

    benchmark_commit: str = MINEDOJO_AUDITED_COMMIT
    reward_commit: str = MINECLIP_AUDITED_COMMIT

    benchmark_task_count: int = 3142
    programmatic_task_count: int = 1581
    creative_task_count: int = 1560
    playthrough_task_count: int = 1
    task_categories: tuple[str, ...] = MINEDOJO_TASK_CATEGORIES
    programmatic_families: tuple[str, ...] = MINEDOJO_PROGRAMMATIC_FAMILIES
    programmatic_success_aggregation: str = "any"

    language_prompted_tasks: bool = True
    procedural_3d_world: bool = True
    multimodal_observation_space: bool = True
    compound_action_space: bool = True

    knowledge_youtube_videos: str = "730K+"
    knowledge_youtube_hours: str = "~300K"
    knowledge_youtube_transcript_words: str = "2.2B"
    knowledge_wiki_pages: str = "~7K"
    knowledge_reddit_posts: str = "340K+"
    knowledge_reddit_comments: str = "6.6M"

    mineclip_temporal_max_sequence_length: int = 32
    mineclip_input_resolution: tuple[int, int] = (160, 256)
    mineclip_clip_image_resolution: int = 224
    mineclip_architecture_family: str = "vit_base_p16"
    mineclip_shared_embedding_dim: int = 512
    mineclip_text_context_length: int = 77
    mineclip_text_layers: int = 12
    mineclip_text_heads: int = 8
    mineclip_text_width: int = 512
    mineclip_vision_layers: int = 12
    mineclip_vision_patch_size: int = 16
    mineclip_vision_width: int = 768
    mineclip_vocab_size: int = 49408
    mineclip_mlp_adapter_spec: str = "v0-2.t0"
    mineclip_pool_variants: tuple[str, ...] = MINECLIP_VARIANTS
    mineclip_attention_pool_spec: str = "attn.d2.nh8.glusw"
    mineclip_average_pool_spec: str = "avg"
    mineclip_attention_checkpoint_md5: str = "b5ece9198337cfd117a3bfbd921e56da"
    mineclip_average_checkpoint_md5: str = "d97a07f2830095a2016a8da22abcff52"
    mineclip_video_text_similarity_reward: bool = True
    mineagent_language_conditioned: bool = True
    mineagent_discrete_control: bool = True
    mineagent_deterministic_eval_uses_mode: bool = True
    mineagent_actor_action_dims: tuple[int, ...] = (3, 3, 4, 25, 25, 8)
    mineagent_demo_environment_action_dims: int = 8
    mineagent_demo_forces_sixth_action_zero: bool = True
    mineagent_demo_appends_action_suffix: tuple[int, int] = (0, 0)

    def __post_init__(self) -> None:
        if len(self.benchmark_commit) != 40 or len(self.reward_commit) != 40:
            raise ValueError("MineDojo source commits must be git SHAs")
        if (
            self.programmatic_task_count
            + self.creative_task_count
            + self.playthrough_task_count
            != self.benchmark_task_count
        ):
            raise ValueError("MineDojo task category counts drifted")
        if self.task_categories != MINEDOJO_TASK_CATEGORIES:
            raise ValueError("MineDojo task categories drifted")
        if self.programmatic_families != MINEDOJO_PROGRAMMATIC_FAMILIES:
            raise ValueError("MineDojo programmatic families drifted")
        if self.programmatic_success_aggregation != "any":
            raise ValueError(
                "MineDojo paper-consistent success aggregation must be logical any"
            )
        if not all((
            self.language_prompted_tasks,
            self.procedural_3d_world,
            self.multimodal_observation_space,
            self.compound_action_space,
            self.mineclip_video_text_similarity_reward,
            self.mineagent_language_conditioned,
            self.mineagent_discrete_control,
            self.mineagent_deterministic_eval_uses_mode,
            self.mineagent_demo_forces_sixth_action_zero,
        )):
            raise ValueError("MineDojo core embodied semantics drifted")
        if self.mineclip_temporal_max_sequence_length != 32:
            raise ValueError(
                "MineCLIP temporal max sequence length drifted"
            )
        if self.mineclip_input_resolution != (160, 256):
            raise ValueError("MineCLIP input resolution drifted")
        if self.mineclip_clip_image_resolution != 224:
            raise ValueError("MineCLIP CLIP image resolution drifted")
        if self.mineclip_architecture_family != "vit_base_p16":
            raise ValueError("MineCLIP architecture family drifted")
        if self.mineclip_shared_embedding_dim != 512:
            raise ValueError("MineCLIP shared embedding dimension drifted")
        if (
            self.mineclip_text_context_length,
            self.mineclip_text_layers,
            self.mineclip_text_heads,
            self.mineclip_text_width,
        ) != (77, 12, 8, 512):
            raise ValueError("MineCLIP text encoder semantics drifted")
        if (
            self.mineclip_vision_layers,
            self.mineclip_vision_patch_size,
            self.mineclip_vision_width,
        ) != (12, 16, 768):
            raise ValueError("MineCLIP vision encoder semantics drifted")
        if self.mineclip_vocab_size != 49408:
            raise ValueError("MineCLIP vocabulary size drifted")
        if self.mineclip_pool_variants != MINECLIP_VARIANTS:
            raise ValueError("MineCLIP pooling variants drifted")
        if self.mineclip_mlp_adapter_spec != "v0-2.t0":
            raise ValueError("MineCLIP paper-release adapter spec drifted")
        if self.mineagent_actor_action_dims != (3, 3, 4, 25, 25, 8):
            raise ValueError("MineAgent actor action dimensions drifted")
        if (
            self.mineagent_demo_environment_action_dims != 8
            or self.mineagent_demo_appends_action_suffix != (0, 0)
        ):
            raise ValueError("MineAgent demo action projection drifted")


MINEDOJO_REFERENCE_FIDELITY = MineDojoReferenceFidelity()


__all__ = [
    "MINECLIP_VARIANTS",
    "MINEDOJO_PROGRAMMATIC_FAMILIES",
    "MINEDOJO_REFERENCE_FIDELITY",
    "MINEDOJO_TASK_CATEGORIES",
    "MineDojoReferenceFidelity",
]
