from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    run_id: str
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    study_id: str | None = None
    condition_id: str | None = None
    lifetime_id: str | None = None
    branch_id: str | None = None
    task_id: str | None = None
    decision_cycle_id: str | None = None
    checkpoint_id: str | None = None
    operation_id: str | None = None
    component_id: str | None = None
    participant_generations: tuple[tuple[str, str], ...] = ()
    platform_generation: str | None = None

    def __post_init__(self) -> None:
        roles = [role for role, _ in self.participant_generations]
        if len(roles) != len(set(roles)):
            raise ValueError("ExecutionContext participant generation roles must be unique")
        if tuple(sorted(self.participant_generations)) != self.participant_generations:
            object.__setattr__(self, "participant_generations", tuple(sorted(self.participant_generations)))

    def generation(self, role: str) -> str | None:
        return next((generation for current, generation in self.participant_generations if current == role), None)

    def with_generation(self, role: str, generation: str | None) -> "ExecutionContext":
        rows = dict(self.participant_generations)
        if generation is None:
            rows.pop(role, None)
        else:
            rows[role] = generation
        return replace(self, participant_generations=tuple(sorted(rows.items())))

    def child(
        self,
        *,
        span_id: str,
        operation_id: str | None = None,
        component_id: str | None = None,
    ) -> "ExecutionContext":
        return replace(
            self,
            span_id=span_id,
            parent_span_id=self.span_id,
            operation_id=operation_id,
            component_id=component_id,
        )
