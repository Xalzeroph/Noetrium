from __future__ import annotations

from dataclasses import dataclass
from .registry import MetricRegistry


@dataclass(frozen=True, slots=True)
class CardinalityPolicy:
    forbidden_dimension_names: frozenset[str] = frozenset({
        "request_id", "event_id", "failure_id", "trace_id", "span_id", "task_id",
        "decision_cycle_id", "checkpoint_id", "mutation_id", "artifact_id",
    })


class TelemetryAudit:
    def __init__(self, registry: MetricRegistry, policy: CardinalityPolicy | None = None) -> None:
        self.registry = registry
        self.policy = policy or CardinalityPolicy()

    def run(self) -> tuple[str, ...]:
        errors: list[str] = []
        for name in self.registry.names():
            definition = self.registry.definition(name)
            bad = set(definition.allowed_dimensions) & self.policy.forbidden_dimension_names
            if bad:
                errors.append(f"{name}: forbidden high-cardinality dimensions {sorted(bad)}")
        return tuple(errors)
