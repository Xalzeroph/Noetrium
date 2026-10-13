from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

from collections.abc import Mapping
from dataclasses import dataclass, field, fields, replace

from .canonical import canonical_digest, freeze_json, thaw_json
from .json_value import JsonObject, JsonValue


@dataclass(frozen=True, slots=True)
class GraphExecutionCoordinate:
    """Canonical runtime coordinate binding every diagnostic fact to an execution projection."""

    research_revision_digest: str
    execution_id: str
    cut_id: str
    graph_path: tuple[str, ...]
    graph_node_id: str
    attempt_id: str
    generation: int
    authority_epoch: int | None = None
    coordinate_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("research_revision_digest", "cut_id"):
            value = getattr(self, name)
            if (
                type(value) is not str
                or len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise ValueError(f"GraphExecutionCoordinate {name} must be lowercase SHA-256")
        for name in ("execution_id", "graph_node_id", "attempt_id"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"GraphExecutionCoordinate {name} must be non-empty text")
        if (
            type(self.graph_path) is not tuple
            or not self.graph_path
            or any(type(part) is not str or not part for part in self.graph_path)
        ):
            raise TypeError("GraphExecutionCoordinate graph_path must be a non-empty text tuple")
        if "::".join(self.graph_path) != self.graph_node_id:
            raise ValueError("GraphExecutionCoordinate graph_path/node identity drift")
        if type(self.generation) is not int or self.generation < 1:
            raise ValueError("GraphExecutionCoordinate generation must be positive")
        if self.authority_epoch is not None and (
            type(self.authority_epoch) is not int or self.authority_epoch < 0
        ):
            raise ValueError("GraphExecutionCoordinate authority_epoch must be non-negative or None")
        object.__setattr__(
            self,
            "coordinate_digest",
            canonical_digest(
                {
                    "research_revision_digest": self.research_revision_digest,
                    "execution_id": self.execution_id,
                    "cut_id": self.cut_id,
                    "graph_path": self.graph_path,
                    "graph_node_id": self.graph_node_id,
                    "attempt_id": self.attempt_id,
                    "generation": self.generation,
                    "authority_epoch": self.authority_epoch,
                }
            ),
        )


def graph_execution_coordinate_payload(
    coordinate: GraphExecutionCoordinate,
) -> JsonObject:
    if type(coordinate) is not GraphExecutionCoordinate:
        raise TypeError("graph execution coordinate payload requires typed coordinate")
    return freeze_json(
        {
            "research_revision_digest": coordinate.research_revision_digest,
            "execution_id": coordinate.execution_id,
            "cut_id": coordinate.cut_id,
            "graph_path": coordinate.graph_path,
            "graph_node_id": coordinate.graph_node_id,
            "attempt_id": coordinate.attempt_id,
            "generation": coordinate.generation,
            "authority_epoch": coordinate.authority_epoch,
            "coordinate_digest": coordinate.coordinate_digest,
        }
    )


def graph_execution_coordinate_from_payload(
    value: Mapping[str, object],
) -> GraphExecutionCoordinate:
    if not isinstance(value, Mapping):
        raise TypeError("graph execution coordinate payload must be an object")
    expected = {
        "research_revision_digest", "execution_id", "cut_id", "graph_path",
        "graph_node_id", "attempt_id", "generation", "authority_epoch",
        "coordinate_digest",
    }
    if set(value) != expected:
        raise ValueError("graph execution coordinate payload schema mismatch")
    raw_path = value["graph_path"]
    if not isinstance(raw_path, (tuple, list)):
        raise TypeError("graph execution coordinate graph_path must be a sequence")
    coordinate = GraphExecutionCoordinate(
        research_revision_digest=str(value["research_revision_digest"]),
        execution_id=str(value["execution_id"]),
        cut_id=str(value["cut_id"]),
        graph_path=tuple(str(part) for part in raw_path),
        graph_node_id=str(value["graph_node_id"]),
        attempt_id=str(value["attempt_id"]),
        generation=int(value["generation"]),
        authority_epoch=(
            None if value["authority_epoch"] is None else int(value["authority_epoch"])
        ),
    )
    if coordinate.coordinate_digest != value["coordinate_digest"]:
        raise ValueError("graph execution coordinate digest mismatch")
    return coordinate


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    run_id: str
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    study_id: str | None = None
    experiment_id: str | None = None
    condition_id: str | None = None
    condition_selections: tuple[tuple[str, str], ...] = ()
    intervention_values: tuple[tuple[str, JsonValue], ...] = ()
    assignment_seed: str | None = None
    repetition: int | None = None
    participant_schedule: tuple[tuple[str, ...], ...] = ()
    replay_level: str | None = None
    trial_budget: JsonObject = field(default_factory=dict)
    task_budget: JsonObject = field(default_factory=dict)
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
    execution_tenant_id: str | None = None
    causal_event_refs: tuple[str, ...] = ()
    graph_coordinate: GraphExecutionCoordinate | None = None

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
        if self.experiment_id is not None and (
            type(self.experiment_id) is not str
            or not self.experiment_id.strip()
        ):
            raise ValueError(
                "ExecutionContext experiment_id must be non-empty text or None"
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
            if not isinstance(self.trial_budget, Mapping):
                raise TypeError("ExecutionContext trial_budget must be an object")
        object.__setattr__(
            self,
            "trial_budget",
            freeze_json(self.trial_budget),
        )
        if not isinstance(self.task_budget, Mapping):
            raise TypeError("ExecutionContext task_budget must be an object")
        object.__setattr__(
            self,
            "task_budget",
            freeze_json(self.task_budget),
        )
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
        if type(self.causal_event_refs) is not tuple or any(
            type(reference) is not str
            or len(reference) != 64
            or any(ch not in "0123456789abcdef" for ch in reference)
            for reference in self.causal_event_refs
        ):
            raise TypeError(
                "ExecutionContext causal_event_refs must be lowercase SHA-256 tuple"
            )
        if len(self.causal_event_refs) != len(set(self.causal_event_refs)):
            raise ValueError("ExecutionContext causal_event_refs must be unique")
        if self.graph_coordinate is not None and type(self.graph_coordinate) is not GraphExecutionCoordinate:
            raise TypeError("ExecutionContext graph_coordinate must be typed or None")
        if self.execution_tenant_id is not None:
            if (
                type(self.execution_tenant_id) is not str
                or not self.execution_tenant_id.strip()
            ):
                raise ValueError(
                    "ExecutionContext execution_tenant_id must be non-empty text or None"
                )
            object.__setattr__(
                self,
                "execution_tenant_id",
                self.execution_tenant_id.strip(),
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
                "experiment_id": self.experiment_id,
                "condition_id": self.condition_id,
                "lifetime_id": self.lifetime_id,
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


_CURRENT_EXECUTION_CONTEXT: ContextVar[ExecutionContext | None] = ContextVar(
    "noetrium_execution_context",
    default=None,
)


def current_execution_context() -> ExecutionContext | None:
    """Return the graph-bound execution locus active on this task/thread."""

    return _CURRENT_EXECUTION_CONTEXT.get()


@contextmanager
def execution_context_scope(context: ExecutionContext):
    if not isinstance(context, ExecutionContext):
        raise TypeError("execution context scope requires ExecutionContext")
    token = _CURRENT_EXECUTION_CONTEXT.set(context)
    try:
        yield context
    finally:
        _CURRENT_EXECUTION_CONTEXT.reset(token)


def execution_context_payload(context: ExecutionContext) -> JsonObject:
    """Encode the complete ExecutionContext through one kernel-owned schema."""
    if not isinstance(context, ExecutionContext):
        raise TypeError("execution context payload requires ExecutionContext")
    raw = {
        item.name: getattr(context, item.name)
        for item in fields(ExecutionContext)
    }
    raw["graph_coordinate"] = (
        None
        if context.graph_coordinate is None
        else graph_execution_coordinate_payload(context.graph_coordinate)
    )
    payload = freeze_json(raw)
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
    raw_coordinate = decoded["graph_coordinate"]
    decoded["graph_coordinate"] = (
        None
        if raw_coordinate is None
        else graph_execution_coordinate_from_payload(raw_coordinate)
    )
    for field_name in _CONTEXT_SEQUENCE_FIELDS:
        rows = decoded[field_name]
        if not isinstance(rows, (tuple, list)):
            raise TypeError(f"execution context {field_name} must be a sequence")
        decoded[field_name] = tuple(tuple(row) for row in rows)
    causal_refs = decoded["causal_event_refs"]
    if not isinstance(causal_refs, (tuple, list)):
        raise TypeError("execution context causal_event_refs must be a sequence")
    decoded["causal_event_refs"] = tuple(causal_refs)
    return ExecutionContext(**decoded)
