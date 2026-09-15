from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SweAgent07Fidelity:
    """Paper-era SWE-agent 0.7 ACI protocol used for matched reproduction."""

    source_repository: str = "https://github.com/SWE-agent/SWE-agent"
    source_artifact: str = "config/sweagent_0_7/07.yaml"
    parser_type: str = "thought_action"
    exactly_one_command_per_turn: bool = True
    wait_for_observation_after_command: bool = True
    submit_command: str = "submit"
    interactive_commands_allowed: bool = False
    editor_window_lines: int = 100
    editor_overlap_lines: int = 2
    visible_observation_history: int = 5

    def __post_init__(self) -> None:
        if self.parser_type != "thought_action":
            raise ValueError("matched SWE-agent 0.7 reproduction requires thought_action parsing")
        if not self.exactly_one_command_per_turn or not self.wait_for_observation_after_command:
            raise ValueError("SWE-agent 0.7 requires one command followed by environment feedback")
        if self.submit_command != "submit":
            raise ValueError("SWE-agent 0.7 terminal submission command drifted")
        if self.interactive_commands_allowed:
            raise ValueError("SWE-agent 0.7 environment disallows interactive session commands")
        if (self.editor_window_lines, self.editor_overlap_lines) != (100, 2):
            raise ValueError("SWE-agent 0.7 windowed editor fidelity drifted")
        if self.visible_observation_history != 5:
            raise ValueError("SWE-agent 0.7 exposes the last five observations")


SWE_AGENT_07_FIDELITY = SweAgent07Fidelity()


__all__ = ["SWE_AGENT_07_FIDELITY", "SweAgent07Fidelity"]
