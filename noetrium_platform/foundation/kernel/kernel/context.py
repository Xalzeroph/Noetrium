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
    condition_selections: tuple[tuple[str, str], ...] = ()
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
        if type(self.condition_selections) is not tuple or any(
            type(row) is not tuple
            or len(row) != 2
            or any(type(value) is not str or not value.strip() for value in row)
            for row in self.condition_selections
        ):
            raise TypeError(
                "ExecutionContext condition selections must be "
                "(condition, selection) text pairs"
            )
        condition_ids = tuple(row[0] for row in self.condition_selections)
        if len(condition_ids) != len(set(condition_ids)):
            raise ValueError(
                "ExecutionContext condition selection identities must be unique"
            )
        canonical_conditions = tuple(sorted(self.condition_selections))
        if canonical_conditions != self.condition_selections:
            object.__setattr__(
                self, "condition_selections", canonical_conditions
            )
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
