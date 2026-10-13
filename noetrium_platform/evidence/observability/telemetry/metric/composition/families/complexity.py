from noetrium_platform.evidence.observability.telemetry.metric.api import (
    MetricDefinition,
    MetricKind,
)

H = MetricKind.HISTOGRAM
G = MetricKind.GAUGE
C = MetricKind.COUNTER


def definitions() -> tuple[MetricDefinition, ...]:
    return (
        MetricDefinition(
            "execution.cost.wall",
            H,
            "seconds",
            ("algorithm", "outcome"),
            "Graph-bound execution interval wall time",
        ),
        MetricDefinition(
            "execution.cost.cpu",
            H,
            "seconds",
            ("algorithm", "outcome"),
            "Graph-bound execution interval process CPU time",
        ),
        MetricDefinition(
            "execution.cost.rss",
            G,
            "bytes",
            ("algorithm", "kind"),
            "Graph-bound execution process RSS observation",
        ),
        MetricDefinition(
            "execution.cost.scale",
            G,
            "count",
            ("algorithm", "variable"),
            "Runtime input scale variable for complexity analysis",
        ),
        MetricDefinition(
            "execution.cost.work",
            C,
            "count",
            ("algorithm", "counter"),
            "Exact logical work counter increment",
        ),
        MetricDefinition(
            "execution.cost.stage",
            H,
            "seconds",
            ("algorithm", "kind"),
            "Attributed execution stage duration",
        ),
        MetricDefinition(
            "execution.cost.wait",
            H,
            "seconds",
            ("algorithm", "kind"),
            "Attributed wait duration",
        ),
        MetricDefinition(
            "execution.cost.io",
            C,
            "bytes",
            ("algorithm", "kind"),
            "Attributed I/O volume",
        ),
        MetricDefinition(
            "execution.cost.memory",
            G,
            "bytes",
            ("algorithm", "kind"),
            "Attributed logical or physical memory amount",
        ),
        MetricDefinition(
            "execution.cost.parallelism",
            G,
            "count",
            ("algorithm",),
            "Observed work/span average parallelism",
        ),
        MetricDefinition(
            "execution.cost.time_bound_growth",
            G,
            "count",
            ("algorithm", "bound"),
            "Finite-scale growth proxy of the declared time-complexity bound",
        ),
        MetricDefinition(
            "execution.cost.time_bound_normalized",
            H,
            "seconds",
            ("algorithm", "bound", "clock"),
            "Observed time divided by the declared finite-scale growth proxy",
        ),
    )


__all__ = ["definitions"]
