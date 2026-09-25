from __future__ import annotations

from noetrium_platform.evidence.observability.telemetry.metric.api import MetricDefinition, MetricKind


def definitions() -> tuple[MetricDefinition, ...]:
    C=MetricKind.COUNTER; G=MetricKind.GAUGE; H=MetricKind.HISTOGRAM
    return (
        MetricDefinition('prompt.block.bytes',H,'bytes',('role', 'block'),'Typed prompt block size'),
        MetricDefinition('prompt.bundle.use',C,'count',('role', 'bundle', 'model'),'Exact prompt bundle usage'),
        MetricDefinition('prompt.canary.pass',G,'ratio',('role', 'bundle', 'model'),'Canary pass ratio'),
        MetricDefinition('prompt.compile.latency',H,'seconds',('role', 'result'),'Prompt compilation latency'),
        MetricDefinition('prompt.contract.failures',C,'count',('role', 'reason'),'Prompt identity/contract failures'),
        MetricDefinition('prompt.outcome.success',G,'ratio',('role', 'bundle', 'task_family'),'Observed objective outcome association'),
    )
