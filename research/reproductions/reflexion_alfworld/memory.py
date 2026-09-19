from __future__ import annotations

from dataclasses import dataclass, replace

from .fidelity import REFLEXION_ALFWORLD_FIDELITY


def _reflection(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Reflexion verbal memory must be non-empty text")
    return value.strip()


@dataclass(frozen=True, slots=True)
class ReflexionTaskState:
    """Method-owned cross-trial verbal reinforcement state for one ALFWorld task."""

    task_id: str
    reflections: tuple[str, ...] = ()
    solved: bool = False
    skip: bool = False
    completed_trials: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("Reflexion task_id is required")
        if not isinstance(self.reflections, tuple):
            raise TypeError("Reflexion reflections must be a tuple")
        object.__setattr__(self, "reflections", tuple(_reflection(item) for item in self.reflections))
        if not isinstance(self.solved, bool) or not isinstance(self.skip, bool):
            raise TypeError("Reflexion solved/skip flags must be boolean")
        if type(self.completed_trials) is not int or self.completed_trials < 0:
            raise ValueError("completed_trials must be non-negative")
        if self.completed_trials > REFLEXION_ALFWORLD_FIDELITY.max_trials:
            raise ValueError("completed_trials exceeds matched Reflexion protocol")

    @property
    def visible_reflections(self) -> tuple[str, ...]:
        return self.reflections[-REFLEXION_ALFWORLD_FIDELITY.reflection_memory_window :]

    @property
    def memory_view(self) -> tuple[str, ...]:
        return self.visible_reflections

    @property
    def skipped(self) -> bool:
        return self.skip

    @property
    def active(self) -> bool:
        return not self.solved and not self.skip

    @property
    def should_attempt(self) -> bool:
        return not self.solved

    @property
    def should_reflect(self) -> bool:
        return self.active

    def append_reflection(self, reflection: str) -> "ReflexionTaskState":
        if not self.should_reflect:
            raise ValueError("Reflexion cannot add verbal memory for solved/skipped task")
        return replace(self, reflections=(*self.reflections, _reflection(reflection)))

    def mark_solved(self) -> "ReflexionTaskState":
        return replace(self, solved=True)

    def complete_trial(self, *, success: bool) -> "ReflexionTaskState":
        if not self.active:
            raise ValueError("solved or skipped Reflexion tasks cannot consume another trial")
        if self.completed_trials >= REFLEXION_ALFWORLD_FIDELITY.max_trials:
            raise ValueError("Reflexion trial budget exhausted")
        return replace(self, completed_trials=self.completed_trials + 1, solved=bool(success))


__all__ = ["ReflexionTaskState"]