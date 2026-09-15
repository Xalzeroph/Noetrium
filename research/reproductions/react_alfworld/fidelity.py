from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReactAlfworldFidelity:
    """Scientific protocol extracted from the original ReAct ALFWorld run."""

    source_repository: str = "https://github.com/ysymyth/ReAct"
    source_artifact: str = "alfworld.ipynb"
    environment_split: str = "eval_out_of_distribution"
    reference_model: str = "text-davinci-002"
    temperature: float = 0.0
    max_output_tokens: int = 100
    stop_sequences: tuple[str, ...] = ("\n",)
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    max_turns: int = 49
    expected_task_count: int = 134
    think_prefix: str = "think:"
    think_observation: str = "OK."
    demonstrations_per_task_family: int = 2
    task_families: tuple[str, ...] = (
        "pick_and_place",
        "pick_clean_then_place",
        "pick_heat_then_place",
        "pick_cool_then_place",
        "look_at_obj",
        "pick_two_obj",
    )

    def __post_init__(self) -> None:
        if self.environment_split != "eval_out_of_distribution":
            raise ValueError("matched ReAct ALFWorld reproduction requires OOD evaluation split")
        if self.temperature != 0.0:
            raise ValueError("matched ReAct ALFWorld reproduction requires temperature=0")
        if self.max_output_tokens != 100:
            raise ValueError("matched ReAct ALFWorld reproduction requires max_output_tokens=100")
        if self.stop_sequences != ("\n",):
            raise ValueError("matched ReAct ALFWorld reproduction requires newline stop")
        if self.max_turns != 49:
            raise ValueError("matched ReAct ALFWorld reproduction requires 49 turns")
        if self.expected_task_count != 134:
            raise ValueError("matched ReAct ALFWorld reproduction requires 134 tasks")
        if self.demonstrations_per_task_family != 2:
            raise ValueError("matched ReAct ALFWorld reproduction requires two demonstrations per family")
        if len(self.task_families) != 6 or len(set(self.task_families)) != 6:
            raise ValueError("matched ReAct ALFWorld reproduction requires six unique task families")


REACT_ALFWORLD_FIDELITY = ReactAlfworldFidelity()


__all__ = ["REACT_ALFWORLD_FIDELITY", "ReactAlfworldFidelity"]
