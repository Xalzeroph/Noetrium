from __future__ import annotations

from noetrium_platform.evidence.observability.telemetry.metric.api import MetricDefinition, MetricKind


def definitions() -> tuple[MetricDefinition, ...]:
    C=MetricKind.COUNTER; G=MetricKind.GAUGE; H=MetricKind.HISTOGRAM
    return (
        MetricDefinition('model.batch.size',H,'requests',('model', 'engine', 'replica'),'Continuous batch size'),
        MetricDefinition('model.batch.tokens',H,'tokens',('model', 'engine', 'replica'),'Continuous batch tokens'),
        MetricDefinition('model.e2e.latency',H,'seconds',('model', 'engine', 'replica'),'Server request end-to-end latency'),
        MetricDefinition('model.health.latency',H,'seconds',('model', 'engine', 'replica'),'Readiness/health probe latency'),
        MetricDefinition('model.kv_cache.bytes',G,'bytes',('model', 'engine', 'replica'),'KV cache bytes'),
        MetricDefinition('model.kv_cache.usage',G,'ratio',('model', 'engine', 'replica'),'KV cache occupancy'),
        MetricDefinition('model.load.duration',H,'seconds',('model', 'engine', 'result'),'Model load time'),
        MetricDefinition('model.preemptions',C,'count',('model', 'engine', 'replica'),'Scheduler preemptions'),
        MetricDefinition('model.prefix_cache.hit',C,'count',('model', 'engine', 'replica'),'Prefix-cache hits'),
        MetricDefinition('model.prefix_cache.miss',C,'count',('model', 'engine', 'replica'),'Prefix-cache misses'),
        MetricDefinition('model.process.restarts',C,'count',('model', 'engine', 'cause'),'Exact-model process restarts'),
        MetricDefinition('model.requests.inflight',G,'requests',('model', 'engine', 'replica'),'In-flight server requests'),
        MetricDefinition('model.requests.queued',G,'requests',('model', 'engine', 'replica'),'Queued server requests'),
        MetricDefinition('model.throughput',G,'tokens_per_second',('model', 'engine', 'replica', 'direction'),'Serving throughput'),
        MetricDefinition('model.tpot',H,'seconds_per_token',('model', 'engine', 'replica'),'Time per output token'),
        MetricDefinition('model.ttft',H,'seconds',('model', 'engine', 'replica'),'Time to first token'),
        MetricDefinition('model.warmup.duration',H,'seconds',('model', 'engine', 'result'),'Warmup duration'),
    )
