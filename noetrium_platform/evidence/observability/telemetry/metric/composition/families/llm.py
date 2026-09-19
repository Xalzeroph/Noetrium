from __future__ import annotations

from noetrium_platform.evidence.observability.telemetry.metric.api import MetricDefinition, MetricKind


def definitions() -> tuple[MetricDefinition, ...]:
    C=MetricKind.COUNTER; G=MetricKind.GAUGE; H=MetricKind.HISTOGRAM
    return (
        MetricDefinition('llm.attempt.latency',H,'seconds',('role', 'model', 'endpoint', 'status', 'stage'),'Physical model attempt'),
        MetricDefinition('llm.attempts',C,'count',('role', 'model', 'endpoint', 'status'),'Physical attempts'),
        MetricDefinition('llm.cache.hit',C,'count',('role', 'cache'),'Semantic cache hits'),
        MetricDefinition('llm.cache.miss',C,'count',('role', 'cache'),'Semantic cache misses'),
        MetricDefinition('llm.contract_repair',C,'count',('role', 'model', 'result'),'Schema repair attempts'),
        MetricDefinition('llm.finish_reason',C,'count',('role', 'model', 'reason'),'Provider finish reasons'),
        MetricDefinition('llm.http_status',C,'count',('role', 'model', 'endpoint', 'status_class'),'HTTP response classes'),
        MetricDefinition('llm.queue_wait',H,'seconds',('role', 'model', 'endpoint'),'Global/admission queue wait'),
        MetricDefinition('llm.request.latency',H,'seconds',('role', 'model', 'endpoint', 'status'),'Logical LLM request latency'),
        MetricDefinition('llm.requests',C,'count',('role', 'model', 'status'),'Logical requests'),
        MetricDefinition('llm.response_parse',H,'seconds',('role', 'model', 'result'),'Response parse/contract latency'),
        MetricDefinition('llm.retry_sleep',H,'seconds',('role', 'model', 'reason'),'Retry backoff duration'),
        MetricDefinition('llm.singleflight.wait',H,'seconds',('role', 'cache'),'Semantic single-flight wait'),
        MetricDefinition('llm.tokens.cached',C,'tokens',('role', 'model'),'Provider-reported cached input tokens'),
        MetricDefinition('llm.tokens.input',C,'tokens',('role', 'model'),'Raw input tokens'),
        MetricDefinition('llm.tokens.output',C,'tokens',('role', 'model'),'Raw output tokens'),
        MetricDefinition('llm.tokens.reasoning',C,'tokens',('role', 'model'),'Provider-reported reasoning tokens'),
    )
