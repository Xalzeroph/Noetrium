from __future__ import annotations

from dataclasses import dataclass

from .source import JARVIS1_PUBLIC_EXECUTABLE_COMMIT


@dataclass(frozen=True, slots=True)
class Jarvis1ReferenceFidelity:
    """TPAMI method semantics and the explicitly partial public executable."""

    public_executable_commit: str = JARVIS1_PUBLIC_EXECUTABLE_COMMIT
    world: str = "minecraft"
    multimodal_inputs: tuple[str, ...] = (
        "visual_observation",
        "human_instruction",
    )
    planner_family: str = "multimodal-language-model"
    controller_family: str = "goal-conditioned-controller"
    memory_role: str = "planning-from-knowledge-and-survival-experience"
    lifelong_self_improvement: bool = True

    public_offline_fixed_memory_only: bool = True
    public_memory_keying: str = "task-keyed"
    public_memory_fields: tuple[str, ...] = (
        "time",
        "status",
        "image",
        "init_inventory",
        "plan",
    )
    public_plan_step_fields: tuple[str, ...] = (
        "goal",
        "type",
        "text",
    )
    public_memory_state_sequence_released: bool = False
    public_memory_action_sequence_released: bool = False
    public_multimodal_descriptor_released: bool = False
    public_multimodal_retrieval_released: bool = False
    public_online_learning_released: bool = False
    public_self_check_released: bool = False

    steve1_text_controller_timeout: int = 500
    steve1_target_reward: float = 1.0

    def __post_init__(self) -> None:
        if len(self.public_executable_commit) != 40:
            raise ValueError("JARVIS-1 executable commit must be full git SHA")
        if self.world != "minecraft":
            raise ValueError("JARVIS-1 world semantics drifted")
        if self.multimodal_inputs != (
            "visual_observation",
            "human_instruction",
        ):
            raise ValueError("JARVIS-1 multimodal inputs drifted")
        if not self.lifelong_self_improvement:
            raise ValueError("JARVIS-1 paper requires lifelong self-improvement")
        if not self.public_offline_fixed_memory_only:
            raise ValueError(
                "public JARVIS-1 executable must remain fixed-memory only"
            )
        if self.public_memory_fields != (
            "time",
            "status",
            "image",
            "init_inventory",
            "plan",
        ):
            raise ValueError("JARVIS-1 public memory record schema drifted")
        if self.public_plan_step_fields != ("goal", "type", "text"):
            raise ValueError("JARVIS-1 public plan schema drifted")
        if any((
            self.public_memory_state_sequence_released,
            self.public_memory_action_sequence_released,
            self.public_multimodal_descriptor_released,
            self.public_multimodal_retrieval_released,
            self.public_online_learning_released,
            self.public_self_check_released,
        )):
            raise ValueError(
                "partial public JARVIS-1 lane must not claim unreleased modules"
            )
        if (
            self.steve1_text_controller_timeout,
            self.steve1_target_reward,
        ) != (500, 1.0):
            raise ValueError("JARVIS-1 public STEVE-I controller defaults drifted")


JARVIS1_REFERENCE_FIDELITY = Jarvis1ReferenceFidelity()

__all__ = [
    "JARVIS1_REFERENCE_FIDELITY",
    "Jarvis1ReferenceFidelity",
]
