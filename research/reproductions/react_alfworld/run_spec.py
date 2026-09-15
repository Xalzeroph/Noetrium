from __future__ import annotations

from dataclasses import dataclass

from .fidelity import REACT_ALFWORLD_FIDELITY


@dataclass(frozen=True, slots=True)
class ReactAlfworldRunSpec:
    """Matched-stack study input without owning any Research Agent OS runtime."""

    method_id: str = "react"
    benchmark_id: str = "alfworld"
    environment_split: str = REACT_ALFWORLD_FIDELITY.environment_split
    expected_task_count: int = REACT_ALFWORLD_FIDELITY.expected_task_count
    max_turns: int = REACT_ALFWORLD_FIDELITY.max_turns
    terminal_authority: str = "environment"
    success_signal: str = "info.won"

    def __post_init__(self) -> None:
        if (self.method_id, self.benchmark_id) != ("react", "alfworld"):
            raise ValueError("ReAct ALFWorld run identity drifted")
        if self.environment_split != REACT_ALFWORLD_FIDELITY.environment_split:
            raise ValueError("ReAct ALFWorld split drifted")
        if self.expected_task_count != REACT_ALFWORLD_FIDELITY.expected_task_count:
            raise ValueError("ReAct ALFWorld task cardinality drifted")
        if self.max_turns != REACT_ALFWORLD_FIDELITY.max_turns:
            raise ValueError("ReAct ALFWorld turn budget drifted")
        if self.terminal_authority != "environment":
            raise ValueError("matched ReAct ALFWorld termination must remain environment-driven")
        if self.success_signal != "info.won":
            raise ValueError("matched ReAct ALFWorld success must use ALFWorld info.won")


REACT_ALFWORLD_RUN_SPEC = ReactAlfworldRunSpec()


__all__ = ["REACT_ALFWORLD_RUN_SPEC", "ReactAlfworldRunSpec"]
