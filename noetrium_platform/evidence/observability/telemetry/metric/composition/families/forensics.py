from __future__ import annotations

from noetrium_platform.evidence.observability.telemetry.metric.api import MetricDefinition, MetricKind


def definitions() -> tuple[MetricDefinition, ...]:
    C=MetricKind.COUNTER; G=MetricKind.GAUGE; H=MetricKind.HISTOGRAM
    return (
        MetricDefinition('forensics.chain.rows',G,'count',('chain',),'Authoritative chain rows'),
        MetricDefinition('forensics.crash_bundle.duration',H,'seconds',('result',),'Crash bundle build/publish time'),
        MetricDefinition('forensics.evidence.bytes',G,'bytes',('kind',),'Stored forensic evidence volume'),
        MetricDefinition('forensics.index.rows',G,'count',('kind',),'Disposable index rows'),
        MetricDefinition('forensics.query.latency',H,'seconds',('query',),'Operator diagnostic query latency'),
        MetricDefinition('recovery.attempts',C,'count',('scope', 'result', 'cause'),'Recovery attempts'),
        MetricDefinition('recovery.duration',H,'seconds',('scope', 'result'),'Exact-state recovery time'),
        MetricDefinition('recovery.step.duration',H,'seconds',('scope', 'step', 'result'),'Recovery step time'),
    )
