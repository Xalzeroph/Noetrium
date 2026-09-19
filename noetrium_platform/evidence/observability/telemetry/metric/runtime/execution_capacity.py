from __future__ import annotations

import time

from noetrium_platform.evidence.observability.projection.api import ExecutionCapacityFacts
from noetrium_platform.evidence.observability.telemetry.metric.api import MetricObservation


def _row(metric: str, value: float, timestamp: float, **dimensions: str) -> MetricObservation:
    return MetricObservation(metric, float(value), timestamp, tuple(sorted(dimensions.items())))


def project_execution_capacity_metrics(
    facts: ExecutionCapacityFacts,
    *,
    timestamp: float | None = None,
) -> tuple[MetricObservation, ...]:
    """Project observability-owned execution facts into metric observations."""

    now = time.time() if timestamp is None else float(timestamp)
    rows: list[MetricObservation] = [
        _row("execution.admission.oldest_wait", facts.oldest_wait_seconds, now),
    ]
    for item in facts.admission_scopes:
        dims = {"scope": item.scope, "id": item.identity}
        rows.append(_row("execution.admission.inflight", item.in_flight, now, **dims))
        rows.append(_row("execution.admission.waiting", item.waiting, now, **dims))
    for lane in facts.serial_mailboxes:
        fill = min(1.0, lane.queued_work_items / lane.capacity) if lane.capacity else 0.0
        dims = {"lane": lane.lane_id, "owner": lane.owner_group_id}
        rows.append(_row("execution.serial.mailbox.depth", lane.queued_work_items, now, **dims))
        rows.append(_row("execution.serial.mailbox.fill", fill, now, **dims))
        rows.append(_row("execution.serial.logical_outstanding", lane.logical_outstanding, now, **dims))
    return tuple(rows)


__all__ = ["project_execution_capacity_metrics"]
