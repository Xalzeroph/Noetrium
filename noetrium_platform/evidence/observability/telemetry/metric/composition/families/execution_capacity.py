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
