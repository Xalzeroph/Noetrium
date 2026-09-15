from __future__ import annotations

from dataclasses import dataclass, replace

from .fidelity import REFLEXION_ALFWORLD_FIDELITY


@dataclass(frozen=True, slots=True)
class ReflexionTaskState:
    """Method-owned verbal reinforcement state for one fixed ALFWorld task."""

    task_id: str
    completed_trials: int = 0
    solved: bool = False
    skipped: bool = False
    reflections: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("Reflexion task_id is required")
        if type(self.completed_trials) is not int or self.completed_trials < 0:
            raise ValueError("completed_trials must be non-negative")
        if self.completed_trials > REFLEXION_ALFWORLD_FIDELITY.num_trials:
            raise ValueError("completed_trials exceeds matched Reflexion protocol")
        if any(not isinstance(item, str) or not item.strip() for item in self.reflections):
            raise ValueError("reflections must contain non-empty text")

    @property
    def active(self) -> bool:
        return not self.solved and not self.skipped

    @property
    def memory_view(self) -> tuple[str, ...]:
        limit = REFLEXION_ALFWORLD_FIDELITY.max_visible_reflections
        return self.reflections[-limit:]

    def complete_trial(self, *, success: bool) -> "ReflexionTaskState":
        if not self.active:
            raise ValueError("solved or skipped Reflexion tasks cannot consume another trial")
        if self.completed_trials >= REFLEXION_ALFWORLD_FIDELITY.num_trials:
            raise ValueError("Reflexion trial budget exhausted")
        return replace(
            self,
            completed_trials=self.completed_trials + 1,
            solved=bool(success),
        )

    def append_reflection(self, reflection: str) -> "ReflexionTaskState":
        if not self.active:
            raise ValueError("reflection is valid only for an unsolved active task")
        if self.completed_trials <= 0:
            raise ValueError("reflection requires a completed failed trial")
        if not isinstance(reflection, str) or not reflection.strip():
            raise ValueError("reflection must be non-empty text")
        return replace(self, reflections=(*self.reflections, reflection.strip()))


def should_reflect(before: ReflexionTaskState, after: ReflexionTaskState) -> bool:
    """Return the original method's post-trial reflection eligibility."""

    if before.task_id != after.task_id:
        raise ValueError("Reflexion state transition changed task identity")
    return (
        before.active
        and after.active
        and after.completed_trials == before.completed_trials + 1
        and not after.solved
    )


__all__ = ["ReflexionTaskState", "should_reflect"]
