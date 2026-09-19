from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from noetrium_platform.foundation.kernel.kernel import canonical_digest

from .rows import PendingMetric


def _metric_document(row: PendingMetric) -> dict[str, object]:
    context = row.context
    return {
        "metric": row.metric,
        "value": row.value,
        "timestamp": row.timestamp,
        "dimensions": row.dimensions,
        "context": {
            "run_id": context.run_id,
            "trace_id": context.trace_id,
            "span_id": context.span_id,
            "parent_span_id": context.parent_span_id,
            "study_id": context.study_id,
            "condition_id": context.condition_id,
            "lifetime_id": context.lifetime_id,
            "branch_id": context.branch_id,
            "task_id": context.task_id,
            "decision_cycle_id": context.decision_cycle_id,
            "checkpoint_id": context.checkpoint_id,
            "operation_id": context.operation_id,
            "component_id": context.component_id,
            "participant_generations": context.participant_generations,
            "platform_generation": context.platform_generation,
        },
    }


@dataclass(frozen=True, slots=True)
class MetricExportBatch:
    """Immutable operational-metric handoff with deterministic identity."""

    rows: tuple[PendingMetric, ...]
    batch_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.rows) is not tuple or not self.rows:
            raise ValueError("metric export batch requires at least one row")
        if any(type(row) is not PendingMetric for row in self.rows):
            raise TypeError("metric export batch rows must be PendingMetric")
        object.__setattr__(
            self,
            "batch_id",
            canonical_digest(
                {
                    "schema": "noetrium.metric-export-batch.v1",
                    "rows": tuple(_metric_document(row) for row in self.rows),
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class MetricExportReceipt:
    """Exporter acknowledgement for one exact immutable batch."""

    batch_id: str
    accepted_count: int

    def __post_init__(self) -> None:
        if type(self.batch_id) is not str or len(self.batch_id) != 64:
            raise ValueError("metric export receipt batch_id must be SHA-256")
        if any(char not in "0123456789abcdef" for char in self.batch_id):
            raise ValueError("metric export receipt batch_id must be lowercase SHA-256")
        if type(self.accepted_count) is not int or self.accepted_count < 0:
            raise ValueError("metric export receipt accepted_count must be non-negative")


class MetricExporterPort(Protocol):
    """Operational export mechanism; owns no metric or scientific authority."""

    def export(self, batch: MetricExportBatch) -> MetricExportReceipt: ...

    def flush(self) -> None: ...

    def close(self) -> None: ...


__all__ = ["MetricExportBatch", "MetricExporterPort", "MetricExportReceipt"]
