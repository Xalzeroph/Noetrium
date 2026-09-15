from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReflexionAlfworldFidelity:
    """Scientific protocol extracted from the official Reflexion ALFWorld run."""

    source_repository: str = "https://github.com/noahshinn/reflexion"
    source_artifacts: tuple[str, ...] = (
        "alfworld_runs/alfworld_trial.py",
        "alfworld_runs/main.py",
        "alfworld_runs/generate_reflections.py",
        "alfworld_runs/run_reflexion.sh",
    )
    environment_split: str = "eval_out_of_distribution"
    reference_model: str = "gpt-3.5-turbo"
    num_trials: int = 10
    num_environments: int = 134
    max_turns_per_trial: int = 49
    max_visible_reflections: int = 3
    think_prefix: str = "think:"
    think_observation: str = "OK."
    reflection_after_failed_trial_only: bool = True

    def __post_init__(self) -> None:
        if self.environment_split != "eval_out_of_distribution":
            raise ValueError("matched Reflexion ALFWorld reproduction requires OOD evaluation")
        if self.num_trials != 10 or self.num_environments != 134:
            raise ValueError("matched Reflexion ALFWorld reproduction requires 10 trials over 134 environments")
        if self.max_turns_per_trial != 49:
            raise ValueError("matched Reflexion ALFWorld reproduction requires 49 turns per trial")
        if self.max_visible_reflections != 3:
            raise ValueError("matched Reflexion ALFWorld reproduction exposes at most three prior reflections")
        if not self.reflection_after_failed_trial_only:
            raise ValueError("Reflexion memory updates are defined only after failed trials")


REFLEXION_ALFWORLD_FIDELITY = ReflexionAlfworldFidelity()


__all__ = ["REFLEXION_ALFWORLD_FIDELITY", "ReflexionAlfworldFidelity"]
