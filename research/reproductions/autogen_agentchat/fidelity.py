from __future__ import annotations

from dataclasses import dataclass


AUTOGEN_PAPER_ERA_COMMIT = "904b293aa47c0e87e27e127254ce4f17a391048c"


@dataclass(frozen=True, slots=True)
class AutoGenAgentChatFidelity:
    """Early AutoGen AgentChat semantics before later framework rewrites."""

    paper_uri: str = "https://arxiv.org/abs/2308.08155"
    source_repository: str = "https://github.com/microsoft/autogen"
    audited_commit: str = AUTOGEN_PAPER_ERA_COMMIT
    groupchat_artifact: str = "autogen/agentchat/groupchat.py"
    user_proxy_artifact: str = "autogen/agentchat/user_proxy_agent.py"
    agents_are_customizable_conversable_participants: bool = True
    supports_llm_human_tool_combinations: bool = True
    groupchat_default_max_round: int = 10
    groupchat_broadcast_excludes_speaker: bool = True
    next_speaker_selected_from_conversation: bool = True
    invalid_or_failed_speaker_selection_falls_back_round_robin: bool = True
    admin_can_take_over_on_interrupt: bool = True
    user_proxy_default_human_input_mode: str = "ALWAYS"
    user_proxy_llm_auto_reply_default: bool = False
    user_proxy_code_execution_enabled_by_default: bool = True
    user_proxy_default_docker_code_execution: bool = True
    human_input_modes: tuple[str, ...] = ("ALWAYS", "TERMINATE", "NEVER")

    def __post_init__(self) -> None:
        if len(self.audited_commit) != 40:
            raise ValueError("AutoGen audited commit must be a git SHA")
        if not self.agents_are_customizable_conversable_participants:
            raise ValueError("AutoGen conversable-agent semantics drifted")
        if not self.supports_llm_human_tool_combinations:
            raise ValueError("AutoGen mixed participant capability semantics drifted")
        if self.groupchat_default_max_round != 10:
            raise ValueError("AutoGen GroupChat default max_round drifted")
        if not all((
            self.groupchat_broadcast_excludes_speaker,
            self.next_speaker_selected_from_conversation,
            self.invalid_or_failed_speaker_selection_falls_back_round_robin,
            self.admin_can_take_over_on_interrupt,
        )):
            raise ValueError("AutoGen GroupChat routing semantics drifted")
        if self.user_proxy_default_human_input_mode != "ALWAYS":
            raise ValueError("AutoGen UserProxy human-input default drifted")
        if self.user_proxy_llm_auto_reply_default:
            raise ValueError("AutoGen UserProxy must default to no LLM auto reply")
        if not self.user_proxy_code_execution_enabled_by_default:
            raise ValueError("AutoGen UserProxy code execution default drifted")
        if not self.user_proxy_default_docker_code_execution:
            raise ValueError("AutoGen UserProxy Docker execution default drifted")
        if self.human_input_modes != ("ALWAYS", "TERMINATE", "NEVER"):
            raise ValueError("AutoGen human-input modes drifted")


AUTOGEN_AGENTCHAT_FIDELITY = AutoGenAgentChatFidelity()


__all__ = [
    "AUTOGEN_AGENTCHAT_FIDELITY",
    "AUTOGEN_PAPER_ERA_COMMIT",
    "AutoGenAgentChatFidelity",
]
