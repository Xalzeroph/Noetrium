from __future__ import annotations

from dataclasses import dataclass


LIVE_SWE_AGENT_V1_COMMIT = "f780bc5886b18eaa3b12e91c67740c3824d70b43"


@dataclass(frozen=True, slots=True)
class LiveSWEAgentFidelity:
    """Fidelity contract for Live-SWE-agent v1.0.0.

    Live tool/scaffold creation is method semantics. Noetrium should provide the
    generic command capability guard, isolated execution, effect evidence,
    artifact lineage and rollback/recovery without deciding which tools the
    agent invents or when such invention is scientifically useful.
    """

    paper_uri: str = "https://arxiv.org/abs/2511.13646"
    source_repository: str = "https://github.com/OpenAutoCoder/live-swe-agent"
    release_tag: str = "v1.0.0"
    audited_commit: str = LIVE_SWE_AGENT_V1_COMMIT
    source_artifact: str = "config/livesweagent.yaml"
    base_scaffold: str = "mini-swe-agent"
    one_action_per_turn: bool = True
    action_interface: str = "bash"
    runtime_tool_creation: bool = True
    trajectory_reflection_before_tool_creation: bool = True
    created_tools_are_python_cli_programs: bool = True
    task_completion_command: str = "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
    terminal_completion_command_is_irreversible: bool = True
    environment_changes_are_new_subshell_per_action: bool = True
    default_step_limit: float = 0.0
    default_cost_limit: float = 3.0

    def __post_init__(self) -> None:
        if len(self.audited_commit) != 40:
            raise ValueError("Live-SWE-agent audited commit must be a git SHA")
        if self.release_tag != "v1.0.0" or self.base_scaffold != "mini-swe-agent":
            raise ValueError("Live-SWE-agent release/base scaffold drifted")
        if not self.one_action_per_turn or self.action_interface != "bash":
            raise ValueError("Live-SWE-agent ACI requires one bash action per turn")
        if not all((
            self.runtime_tool_creation,
            self.trajectory_reflection_before_tool_creation,
            self.created_tools_are_python_cli_programs,
            self.terminal_completion_command_is_irreversible,
            self.environment_changes_are_new_subshell_per_action,
        )):
            raise ValueError("Live-SWE-agent runtime evolution semantics drifted")
        if self.task_completion_command != "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT":
            raise ValueError("Live-SWE-agent completion command drifted")
        if (self.default_step_limit, self.default_cost_limit) != (0.0, 3.0):
            raise ValueError("Live-SWE-agent v1.0.0 budget defaults drifted")


LIVE_SWE_AGENT_FIDELITY = LiveSWEAgentFidelity()


__all__ = [
    "LIVE_SWE_AGENT_FIDELITY",
    "LIVE_SWE_AGENT_V1_COMMIT",
    "LiveSWEAgentFidelity",
]
