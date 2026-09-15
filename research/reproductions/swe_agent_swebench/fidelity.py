from __future__ import annotations

from dataclasses import dataclass


SWE_AGENT_AUDITED_COMMIT = "3ea751c087f32b16e039a2233dd6eefecef325d5"


@dataclass(frozen=True, slots=True)
class SWEAgentPaperEraFidelity:
    """Paper-era ACI semantics preserved by the official SWE-agent 0.7 config.

    The current repository retains ``config/sweagent_0_7/07.yaml`` explicitly
    as the SWE-agent 0.7 configuration. We pin both that artifact and the
    audited repository revision instead of pretending the 2026 default config
    is the original paper protocol.
    """

    source_repository: str = "https://github.com/SWE-agent/SWE-agent"
    audited_repository_commit: str = SWE_AGENT_AUDITED_COMMIT
    source_artifact: str = "config/sweagent_0_7/07.yaml"
    parser: str = "thought_action"
    file_window_lines: int = 100
    file_window_overlap: int = 2
    history_observations_kept: int = 5
    one_command_per_turn: bool = True
    interactive_commands_supported: bool = False
    submit_command: str = "submit"
    tool_bundles: tuple[str, ...] = (
        "registry",
        "windowed",
        "search",
        "windowed_edit_linting",
        "submit",
    )

    def __post_init__(self) -> None:
        if len(self.audited_repository_commit) != 40:
            raise ValueError("SWE-agent audited commit must be a git SHA")
        if self.parser != "thought_action":
            raise ValueError("SWE-agent 0.7 reproduction requires thought_action parsing")
        if (self.file_window_lines, self.file_window_overlap) != (100, 2):
            raise ValueError("SWE-agent 0.7 file-window semantics drifted")
        if self.history_observations_kept != 5:
            raise ValueError("SWE-agent 0.7 reproduction keeps the last five observation outputs")
        if not self.one_command_per_turn or self.interactive_commands_supported:
            raise ValueError("SWE-agent 0.7 command-turn semantics drifted")


@dataclass(frozen=True, slots=True)
class SWEAgentCurrentReferenceFidelity:
    """Current engineering reference, intentionally separate from paper-era fidelity."""

    source_repository: str = "https://github.com/SWE-agent/SWE-agent"
    audited_repository_commit: str = SWE_AGENT_AUDITED_COMMIT
    tool_source_artifact: str = "sweagent/tools/tools.py"
    history_source_artifact: str = "sweagent/agent/history_processors.py"
    default_config_artifact: str = "config/default.yaml"
    parser: str = "function_calling"
    execution_timeout_seconds: int = 30
    install_timeout_seconds: int = 300
    total_execution_timeout_seconds: int = 1800
    max_consecutive_execution_timeouts: int = 3
    cache_control_last_n_messages: int = 2

    def __post_init__(self) -> None:
        if self.parser != "function_calling":
            raise ValueError("current SWE-agent default uses function calling")
        if (
            self.execution_timeout_seconds,
            self.install_timeout_seconds,
            self.total_execution_timeout_seconds,
            self.max_consecutive_execution_timeouts,
        ) != (30, 300, 1800, 3):
            raise ValueError("current SWE-agent timeout semantics drifted")
        if self.cache_control_last_n_messages != 2:
            raise ValueError("current SWE-agent default cache-control window drifted")


SWE_AGENT_PAPER_ERA_FIDELITY = SWEAgentPaperEraFidelity()
SWE_AGENT_CURRENT_REFERENCE_FIDELITY = SWEAgentCurrentReferenceFidelity()


__all__ = [
    "SWE_AGENT_AUDITED_COMMIT",
    "SWE_AGENT_CURRENT_REFERENCE_FIDELITY",
    "SWE_AGENT_PAPER_ERA_FIDELITY",
    "SWEAgentCurrentReferenceFidelity",
    "SWEAgentPaperEraFidelity",
]
