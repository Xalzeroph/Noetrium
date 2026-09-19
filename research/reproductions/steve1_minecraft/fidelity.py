from __future__ import annotations

from dataclasses import dataclass

from .source import STEVE1_AUDITED_COMMIT


@dataclass(frozen=True, slots=True)
class Steve1ReferenceFidelity:
    source_commit: str = STEVE1_AUDITED_COMMIT
    environment_family: str = "minerl"
    observation_family: str = "raw-pixels"
    action_family: str = "keyboard-mouse-low-level"
    prompt_modalities: tuple[str, ...] = ("text", "visual")

    vpt_conditioning_space: str = "mineclip-latent"
    mineclip_embedding_dim: int = 512
    text_prior_latent_dim: int = 512
    policy_hidden_dim: int = 512
    text_cond_scale: float = 6.0
    visual_cond_scale: float = 7.0
    released_runner_gameplay_length: int = 1000
    runner_fps: int = 30

    stochastic_policy_sampling: bool = True
    classifier_free_guidance: bool = True
    guidance_rule: str = "(1+s)*conditional-s*unconditional"
    recurrent_hidden_state: bool = True

    evaluation_task_count: int = 13
    reported_robustly_completed_tasks: int = 12

    def __post_init__(self) -> None:
        if len(self.source_commit) != 40:
            raise ValueError("STEVE-1 source commit must be full git SHA")
        if self.prompt_modalities != ("text", "visual"):
            raise ValueError("STEVE-1 prompt modality set drifted")
        if (
            self.mineclip_embedding_dim,
            self.text_prior_latent_dim,
            self.policy_hidden_dim,
        ) != (512, 512, 512):
            raise ValueError("STEVE-1 latent dimensions drifted")
        if (self.text_cond_scale, self.visual_cond_scale) != (6.0, 7.0):
            raise ValueError("STEVE-1 released guidance scales drifted")
        if self.released_runner_gameplay_length != 1000:
            raise ValueError("STEVE-1 released gameplay length drifted")
        if not self.stochastic_policy_sampling:
            raise ValueError("STEVE-1 released runner uses stochastic sampling")
        if not self.classifier_free_guidance:
            raise ValueError("STEVE-1 requires classifier-free guidance")
        if not self.recurrent_hidden_state:
            raise ValueError("STEVE-1 VPT controller is recurrent")
        if (
            self.evaluation_task_count,
            self.reported_robustly_completed_tasks,
        ) != (13, 12):
            raise ValueError("STEVE-1 reported early-game result drifted")


STEVE1_REFERENCE_FIDELITY = Steve1ReferenceFidelity()

__all__ = ["STEVE1_REFERENCE_FIDELITY", "Steve1ReferenceFidelity"]
