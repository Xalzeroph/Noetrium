from __future__ import annotations

from dataclasses import dataclass, replace

from .fidelity import REFLEXION_ALFWORLD_FIDELITY


def _reflection(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Reflexion verbal memory must be non-empty text")
    return value.strip()


@dataclass(frozen=True, slots=True)
class ReflexionTaskState:
    """Method-owned cross-trial verbal reinforcement state for one ALFWorld task.

    This is deliberately not a Noetrium AgentMemory implementation. Reflexion
    owns the meaning and update policy of these verbal plans; the Research OS
    only needs to persist/version the resulting downstream method state.
    """

    task_id: str
    reflections: tuple[str, ...] = ()
    solved: bool = False
    skip: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError("Reflexion task_id is required")
        if not isinstance(self.reflections, tuple):
            raise TypeError("Reflexion reflections must be a tuple")
        normalized = tuple(_reflection(item) for item in self.reflections)
        object.__setattr__(self, "reflections", normalized)
        if not isinstance(self.solved, bool) or not isinstance(self.skip, bool):
            raise TypeError("Reflexion solved/skip flags must be boolean")

    @property
    def visible_reflections(self) -> tuple[str, ...]:
        window = REFLEXION_ALFWORLD_FIDELITY.reflection_memory_window
        return self.reflections[-window:]

    @property
    def should_attempt(self) -> bool:
        return not self.solved

    @property
    def should_reflect(self) -> bool:
        return not self.solved and not self.skip

    def append_reflection(self, reflection: str) -> "ReflexionTaskState":
        if not self.should_reflect:
            raise ValueError("Reflexion cannot add verbal memory for solved/skipped task")
        return replace(self, reflections=(*self.reflections, _reflection(reflection)))

    def mark_solved(self) -> "ReflexionTaskState":
        return replace(self, solved=True)


__all__ = ["ReflexionTaskState"]
