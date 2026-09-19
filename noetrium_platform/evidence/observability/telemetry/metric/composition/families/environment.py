from __future__ import annotations

from noetrium_platform.evidence.observability.telemetry.metric.api import MetricDefinition, MetricKind


def definitions() -> tuple[MetricDefinition, ...]:
    C=MetricKind.COUNTER; G=MetricKind.GAUGE; H=MetricKind.HISTOGRAM
    return (
        MetricDefinition('environment.action.latency',H,'seconds',('environment', 'action', 'result'),'Environment action latency'),
        MetricDefinition('environment.bridge.bytes',C,'bytes',('environment', 'direction'),'Bridge bytes'),
        MetricDefinition('environment.bridge.queue',G,'count',('environment', 'direction'),'Bridge queue depth'),
        MetricDefinition('environment.effect.unknown',C,'count',('environment', 'action'),'Effects requiring reconcile'),
        MetricDefinition('environment.observe.latency',H,'seconds',('environment', 'result'),'Environment observation latency'),
        MetricDefinition('environment.reconcile.latency',H,'seconds',('environment', 'action', 'result'),'Effect reconciliation latency'),
        MetricDefinition('environment.world.save',H,'seconds',('environment', 'result'),'World save/checkpoint latency'),
    )
