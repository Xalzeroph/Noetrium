from __future__ import annotations

from noetrium_platform.evidence.observability.telemetry.metric.api import MetricDefinition, MetricKind


def definitions() -> tuple[MetricDefinition, ...]:
    G = MetricKind.GAUGE
    return (
        MetricDefinition(
            "execution.admission.inflight",
            G,
            "count",
            ("scope", "id"),
            "Current admitted physical execution count by admission scope",
        ),
        MetricDefinition(
            "execution.admission.waiting",
            G,
            "count",
            ("scope", "id"),
            "Current execution admission waiter count by admission scope",
        ),
        MetricDefinition(
            "execution.admission.completed",
            G,
            "count",
            ("scope", "id"),
            "Completed execution permits observed by admission scope",
        ),
        MetricDefinition(
            "execution.admission.service_seconds_total",
            G,
            "seconds",
            ("scope", "id"),
            "Cumulative execution service seconds observed by admission scope",
        ),
        MetricDefinition(
            "execution.admission.mean_service_seconds",
            G,
            "seconds",
            ("scope", "id"),
            "Observed mean execution service time by admission scope",
        ),
        MetricDefinition(
            "execution.admission.service_rate",
            G,
            "per_second",
            ("scope", "id"),
            "Observed completion service rate by admission scope",
        ),
        MetricDefinition(
            "execution.admission.oldest_wait",
            G,
            "seconds",
            (),
            "Age of the oldest current admission waiter",
        ),
        MetricDefinition(
            "execution.serial.mailbox.depth",
            G,
            "count",
            ("lane", "owner"),
            "Current queued physical work items in a serial mailbox",
        ),
        MetricDefinition(
            "execution.serial.mailbox.fill",
            G,
            "ratio",
            ("lane", "owner"),
            "Current serial mailbox queue fill ratio",
        ),
        MetricDefinition(
            "execution.serial.logical_outstanding",
            G,
            "count",
            ("lane", "owner"),
            "Logical serial submissions still awaiting completion",
        ),
    )
