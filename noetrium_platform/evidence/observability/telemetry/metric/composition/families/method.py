from __future__ import annotations

from noetrium_platform.evidence.observability.telemetry.metric.api import MetricDefinition, MetricKind


def definitions() -> tuple[MetricDefinition, ...]:
    C=MetricKind.COUNTER; G=MetricKind.GAUGE; H=MetricKind.HISTOGRAM
    return (
        MetricDefinition('method.architecture.edges',G,'count',('method', 'generation'),'Architecture edge count'),
        MetricDefinition('method.architecture.nodes',G,'count',('method', 'generation'),'Architecture node count'),
        MetricDefinition('method.context.tokens',H,'tokens',('method', 'generation'),'Compiled memory context tokens'),
        MetricDefinition('method.evidence.lag',G,'count',('method', 'generation'),'Evidence sequence lag'),
        MetricDefinition('method.evolution.acceptance',C,'count',('method', 'edit', 'decision'),'Candidate decisions'),
        MetricDefinition('method.evolution.opportunity',C,'count',('method', 'eligibility'),'Evolution opportunities'),
        MetricDefinition('method.evolution.proposal',C,'count',('method', 'edit', 'result'),'Structural proposals'),
        MetricDefinition('method.evolution.stage',H,'seconds',('method', 'stage', 'result'),'Evolution stage latency'),
        MetricDefinition('method.materialization.duration',H,'seconds',('method', 'mode', 'result'),'Materialization duration'),
        MetricDefinition('method.materialization.records',H,'count',('method', 'mode'),'Materialized records'),
        MetricDefinition('method.recall.latency',H,'seconds',('method', 'generation', 'strategy'),'Method recall latency'),
        MetricDefinition('method.recall.nodes',H,'count',('method', 'generation', 'strategy'),'Nodes searched/used'),
        MetricDefinition('method.recall.records',H,'count',('method', 'generation', 'strategy'),'Records returned'),
    )
