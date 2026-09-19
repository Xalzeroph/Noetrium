from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.research.provenance import MethodSourceLane
from .source import SOURCE_OFFICIAL_REACT_REPO


@dataclass(frozen=True, slots=True)
class ReactAlfworldFidelity:
    """Method/source fidelity extracted from the original ReAct ALFWorld run.

    Benchmark cut, split, task cardinality and task-family taxonomy are owned
    exclusively by the typed ALFWorld benchmark asset and are intentionally not
    duplicated here.
    """

    source: MethodSourceLane = SOURCE_OFFICIAL_REACT_REPO
    reference_model: str = "text-davinci-002"
    temperature: float = 0.0
    max_output_tokens: int = 100
    stop_sequences: tuple[str, ...] = ("\n",)
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    max_turns: int = 49
    think_prefix: str = "think:"
    think_observation: str = "OK."
    think_steps_environment: bool = True
    demonstrations_per_task_family: int = 2

    def __post_init__(self) -> None:
        if self.temperature != 0.0:
            raise ValueError("matched ReAct ALFWorld reproduction requires temperature=0")
        if self.max_output_tokens != 100:
            raise ValueError("matched ReAct ALFWorld reproduction requires max_output_tokens=100")
        if self.stop_sequences != ("\n",):
            raise ValueError("matched ReAct ALFWorld reproduction requires newline stop")
        if self.max_turns != 49:
            raise ValueError("matched ReAct ALFWorld reproduction requires 49 turns")
        if self.think_steps_environment is not True:
            raise ValueError("released ReAct ALFWorld code steps the environment for think actions")
        if self.demonstrations_per_task_family != 2:
            raise ValueError("matched ReAct ALFWorld reproduction requires two demonstrations per family")


REACT_ALFWORLD_FIDELITY = ReactAlfworldFidelity()

__all__ = ["REACT_ALFWORLD_FIDELITY", "ReactAlfworldFidelity"]
