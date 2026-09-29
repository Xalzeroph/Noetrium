from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields, replace

from .canonical import canonical_digest, freeze_json, thaw_json
from .json_value import JsonObject, JsonValue


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    run_id: str
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    study_id: str | None = None
    condition_id: str | None = None
    condition_selections: tuple[tuple[str, str], ...] = ()
    intervention_values: tuple[tuple[str, JsonValue], ...] = ()
    assignment_seed: str | None = None
    repetition: int | None = None
    participant_schedule: tuple[tuple[str, ...], ...] = ()
    replay_level: str | None = None
    trial_budget: JsonObject = field(default_factory=dict)
    budget_usage: JsonObject = field(default_factory=dict)
    execution_policy_admission_digest: str | None = None
    lifetime_id: str | None = None
    branch_id: str | None = None
    task_id: str | None = None
    decision_cycle_id: str | None = None
    checkpoint_id: str | None = None
    operation_id: str | None = None
    component_id: str | None = None
    participant_generations: tuple[tuple[str, str], ...] = ()
    platform_generation: str | None = None
    participant_context: JsonObject = field(default_factory=dict)

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
        if type(self.intervention_values) is not tuple or any(
            type(row) is not tuple
            or len(row) != 2
            or type(row[0]) is not str
            or not row[0].strip()
            for row in self.intervention_values
        ):
            raise TypeError(
                "ExecutionContext intervention_values must be "
                "(factor_id, JsonValue) pairs"
            )
        intervention_ids = tuple(row[0] for row in self.intervention_values)
        if len(intervention_ids) != len(set(intervention_ids)):
            raise ValueError(
                "ExecutionContext intervention factor identities must be unique"
            )
        frozen_interventions = tuple(
            sorted(
                (
                    factor_id,
                    freeze_json(value),
                )
                for factor_id, value in self.intervention_values
            )
        )
        object.__setattr__(
            self, "intervention_values", frozen_interventions
        )
        if self.assignment_seed is not None and (
            type(self.assignment_seed) is not str
            or not self.assignment_seed.strip()
        ):
            raise ValueError(
                "ExecutionContext assignment_seed must be non-empty text or None"
            )
        if self.repetition is not None and (
            type(self.repetition) is not int or self.repetition < 0
        ):
            raise ValueError(
                "ExecutionContext repetition must be non-negative integer or None"
            )
        if type(self.participant_schedule) is not tuple:
            raise TypeError("ExecutionContext participant_schedule must be tuple")
        schedule_roles: list[str] = []
        for wave in self.participant_schedule:
            if (
                type(wave) is not tuple
                or not wave
                or any(type(role) is not str or not role.strip() for role in wave)
            ):
                raise TypeError(
                    "ExecutionContext participant schedule waves must contain text roles"
                )
            schedule_roles.extend(wave)
        if len(schedule_roles) != len(set(schedule_roles)):
            raise ValueError(
                "ExecutionContext participant schedule roles must be unique"
            )
        if self.replay_level is not None and self.replay_level not in {
            "exact", "checkpoint", "observational"
        }:
            raise ValueError("ExecutionContext replay_level is invalid")
        if not isinstance(self.trial_budget, dict):
            from collections.abc import Mapping
            if not isinstance(self.trial_budget, Mapping):
                raise TypeError("ExecutionContext trial_budget must be an object")
        object.__setattr__(
            self,
            "trial_budget",
            freeze_json(self.trial_budget),
        )
        from collections.abc import Mapping
        if not isinstance(self.budget_usage, Mapping):
            raise TypeError("ExecutionContext budget_usage must be an object")
        object.__setattr__(
            self,
            "budget_usage",
            freeze_json(self.budget_usage),
        )
        if self.execution_policy_admission_digest is not None:
            if (
                type(self.execution_policy_admission_digest) is not str
                or len(self.execution_policy_admission_digest) != 64
                or any(
                    ch not in "0123456789abcdef"
                    for ch in self.execution_policy_admission_digest
                )
            ):
                raise ValueError(
                    "ExecutionContext execution_policy_admission_digest "
                    "must be lowercase SHA-256 or None"
                )
        if not isinstance(self.participant_context, Mapping):
            raise TypeError("ExecutionContext participant_context must be an object")
        object.__setattr__(
            self, "participant_context", freeze_json(self.participant_context)
        )
        roles = [role for role, _ in self.participant_generations]
        if len(roles) != len(set(roles)):
            raise ValueError("ExecutionContext participant generation roles must be unique")
        if tuple(sorted(self.participant_generations)) != self.participant_generations:
            object.__setattr__(self, "participant_generations", tuple(sorted(self.participant_generations)))

    def random_seed(self, namespace: str) -> int:
        if type(namespace) is not str or not namespace.strip():
            raise ValueError(
                "ExecutionContext random seed namespace must be non-empty"
            )
        if self.assignment_seed is None:
            raise RuntimeError(
                "ExecutionContext has no Study assignment seed"
            )
        digest = canonical_digest(
            {
                "schema": "noetrium.execution-random-seed.v1",
                "assignment_seed": self.assignment_seed,
                "repetition": self.repetition,
                "study_id": self.study_id,
                "condition_id": self.condition_id,
                "task_id": self.task_id,
                "namespace": namespace,
            }
        )
        return int(digest[:16], 16)

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


_CONTEXT_SEQUENCE_FIELDS = frozenset({
    "condition_selections",
    "intervention_values",
    "participant_schedule",
    "participant_generations",
})


def execution_context_payload(context: ExecutionContext) -> JsonObject:
    """Encode the complete ExecutionContext through one kernel-owned schema."""
    if not isinstance(context, ExecutionContext):
        raise TypeError("execution context payload requires ExecutionContext")
    payload = freeze_json({
        item.name: getattr(context, item.name)
        for item in fields(ExecutionContext)
    })
    if not isinstance(payload, Mapping):
        raise TypeError("execution context payload must be an object")
    return payload


def execution_context_from_payload(value: JsonObject) -> ExecutionContext:
    """Decode the exact current ExecutionContext schema; no legacy field sets."""
    if not isinstance(value, Mapping):
        raise TypeError("execution context payload must be an object")
    decoded = thaw_json(freeze_json(value))
    if not isinstance(decoded, dict):
        raise TypeError("execution context payload must decode to an object")
    expected = {item.name for item in fields(ExecutionContext)}
    actual = set(decoded)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ValueError(
            "execution context payload schema mismatch: "
            f"missing={missing} unknown={unknown}"
        )
    for field_name in _CONTEXT_SEQUENCE_FIELDS:
        rows = decoded[field_name]
        if not isinstance(rows, (tuple, list)):
            raise TypeError(f"execution context {field_name} must be a sequence")
        decoded[field_name] = tuple(tuple(row) for row in rows)
    return ExecutionContext(**decoded)
