from __future__ import annotations

from dataclasses import dataclass


CAMEL_PAPER_ERA_COMMIT = "6915c00a69447fecb796702dc30dec03681173ac"


@dataclass(frozen=True, slots=True)
class CAMELRolePlayingFidelity:
    """Paper-era CAMEL AI-society role-playing semantics.

    This contract deliberately excludes capabilities added by the modern CAMEL
    framework. Role specification, task inception and alternating dialogue are
    scientific method semantics; Noetrium may only supply generic participant,
    message, model-call, transcript and experiment infrastructure.
    """

    paper_uri: str = "https://arxiv.org/abs/2303.17760"
    source_repository: str = "https://github.com/camel-ai/camel"
    audited_commit: str = CAMEL_PAPER_ERA_COMMIT
    role_playing_artifact: str = "camel/agent/role_playing.py"
    system_message_artifact: str = "camel/generator.py"
    chat_agent_artifact: str = "camel/agent/chat_agent.py"
    participant_count: int = 2
    required_roles: tuple[str, ...] = ("assistant", "user")
    task_specification_default: bool = True
    task_planning_default: bool = False
    role_conditioned_system_messages: bool = True
    task_conditioned_system_messages: bool = True
    initial_instruction_constraint: str = "Instruction_and_Input_only"
    turn_order: tuple[str, ...] = ("user_agent", "assistant_agent")
    independent_agent_histories: bool = True
    reset_both_agents_before_init: bool = True
    token_overflow_terminates_agent: bool = True
    optional_message_window_projection: bool = True

    def __post_init__(self) -> None:
        if len(self.audited_commit) != 40:
            raise ValueError("CAMEL audited commit must be a git SHA")
        if self.participant_count != 2 or self.required_roles != ("assistant", "user"):
            raise ValueError("paper-era CAMEL AI society requires one assistant and one user")
        if not self.task_specification_default or self.task_planning_default:
            raise ValueError("paper-era CAMEL task inception defaults drifted")
        if not self.role_conditioned_system_messages or not self.task_conditioned_system_messages:
            raise ValueError("CAMEL inception system-message semantics drifted")
        if self.turn_order != ("user_agent", "assistant_agent"):
            raise ValueError("CAMEL alternating role-play order drifted")
        if not all((
            self.independent_agent_histories,
            self.reset_both_agents_before_init,
            self.token_overflow_terminates_agent,
            self.optional_message_window_projection,
        )):
            raise ValueError("CAMEL dialogue lifecycle semantics drifted")


CAMEL_ROLE_PLAYING_FIDELITY = CAMELRolePlayingFidelity()


__all__ = [
    "CAMEL_PAPER_ERA_COMMIT",
    "CAMEL_ROLE_PLAYING_FIDELITY",
    "CAMELRolePlayingFidelity",
]
