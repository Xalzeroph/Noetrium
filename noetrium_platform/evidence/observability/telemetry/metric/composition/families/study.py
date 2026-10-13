from __future__ import annotations

from noetrium_platform.evidence.observability.telemetry.metric.api import MetricDefinition, MetricKind


def definitions() -> tuple[MetricDefinition, ...]:
    C=MetricKind.COUNTER; G=MetricKind.GAUGE; H=MetricKind.HISTOGRAM
    return (
        MetricDefinition('study.progress',G,'ratio',('condition',),'Study progress ratio'),
        MetricDefinition('study.queue_wait',H,'seconds',('resource_class',),'Study resource admission wait'),
        MetricDefinition('study.task.duration',H,'seconds',('condition', 'task_family', 'result'),'Task duration'),
        MetricDefinition('study.unit.duration',H,'seconds',('condition', 'result'),'Study unit duration'),
    )
