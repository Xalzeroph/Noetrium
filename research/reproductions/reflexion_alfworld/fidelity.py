from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReflexionAlfworldFidelity:
    """Matched-stack protocol extracted from the original Reflexion ALFWorld run.

    These values are scientific method semantics. They intentionally live in
    the downstream reproduction package rather than the Noetrium Research OS.
    """

    source_repository: str = "https://github.com/noahshinn/reflexion"
    action_source_artifact: str = "alfworld_runs/alfworld_trial.py"
    reflection_source_artifact: str = "alfworld_runs/generate_reflections.py"
    launcher_source_artifact: str = "alfworld_runs/run_reflexion.sh"
    environment_split: str = "eval_out_of_distribution"
    expected_task_count: int = 134
    max_trials: int = 10
    max_turns_per_trial: int = 49
    reference_action_model: str = "gpt-3.5-turbo"
    reference_reflection_model: str = "text-davinci-003"
    action_stop_sequences: tuple[str, ...] = ("\n",)
    action_max_output_tokens: int = 256
    reflection_max_output_tokens: int = 256
    action_candidate_attempts: int = 6
    action_minimum_characters: int = 5
    action_temperature_step: float = 0.2
    reflection_temperature: float = 0.0
    reflection_memory_window: int = 3
    think_prefix: str = "think:"
    think_observation: str = "OK."

    def __post_init__(self) -> None:
        if self.environment_split != "eval_out_of_distribution":
            raise ValueError("matched Reflexion ALFWorld reproduction requires OOD evaluation split")
        if self.expected_task_count != 134:
            raise ValueError("matched Reflexion ALFWorld reproduction requires 134 environments")
        if self.max_trials != 10:
            raise ValueError("matched Reflexion ALFWorld reproduction requires 10 trials")
        if self.max_turns_per_trial != 49:
            raise ValueError("matched Reflexion ALFWorld reproduction requires 49 turns per trial")
        if self.reference_action_model != "gpt-3.5-turbo":
            raise ValueError("matched Reflexion ALFWorld reproduction requires the launcher action model")
        if self.reference_reflection_model != "text-davinci-003":
            raise ValueError("matched Reflexion ALFWorld reproduction requires the original reflection model")
        if self.action_stop_sequences != ("\n",):
            raise ValueError("matched Reflexion ALFWorld reproduction requires newline action stop")
        if self.action_candidate_attempts != 6 or self.action_minimum_characters != 5:
            raise ValueError("matched Reflexion ALFWorld action retry semantics drifted")
        if self.action_temperature_step != 0.2 or self.reflection_temperature != 0.0:
            raise ValueError("matched Reflexion ALFWorld temperature semantics drifted")
        if self.reflection_memory_window != 3:
            raise ValueError("matched Reflexion ALFWorld reproduction keeps the last three reflections")

    def action_temperature(self, attempt: int) -> float:
        if type(attempt) is not int or not 0 <= attempt < self.action_candidate_attempts:
            raise ValueError("Reflexion action attempt is outside the matched retry schedule")
        return attempt * self.action_temperature_step


REFLEXION_ALFWORLD_FIDELITY = ReflexionAlfworldFidelity()


__all__ = ["REFLEXION_ALFWORLD_FIDELITY", "ReflexionAlfworldFidelity"]
