from __future__ import annotations

from noetrium_platform.evidence.observability.telemetry.metric.api import MetricDefinition, MetricKind


def definitions() -> tuple[MetricDefinition, ...]:
    C=MetricKind.COUNTER; G=MetricKind.GAUGE; H=MetricKind.HISTOGRAM
    return (
        MetricDefinition('runtime.control.action.count',C,'count',('action','result','mutating'),'Exact runtime control action attempts'),
        MetricDefinition('runtime.control.action.latency',H,'seconds',('action','result','mutating'),'Exact runtime control action latency'),
        MetricDefinition('runtime.control.reconcile',C,'count',('scope',),'Runtime reconcile actions'),
        MetricDefinition('runtime.control.exact_service_start',C,'count',('result',),'Exact frozen model-service starts'),
        MetricDefinition('runtime.control.qualification',C,'count',('result',),'Live runtime qualification verifications'),
        MetricDefinition('runtime.control.recovery_round',C,'count',('action','round'),'Bounded in-command runtime recovery rounds'),
        MetricDefinition('runtime.recovery.lease.conflicts',C,'count',('resource_class',),'Recovery lease acquisition conflicts'),
        MetricDefinition('operation.failures',C,'count',('component', 'domain', 'code', 'stage'),'Structured operation failures'),
        MetricDefinition('operation.inflight',G,'operations',('component', 'operation'),'Current in-flight operations'),
        MetricDefinition('operation.latency',H,'seconds',('component', 'operation', 'status'),'Cross-component operation latency'),
        MetricDefinition('operation.payload.bytes',H,'bytes',('component', 'operation', 'direction'),'Operation payload size'),
        MetricDefinition('operation.queue_wait',H,'seconds',('component', 'operation'),'Operation admission wait'),
        MetricDefinition('runtime.context_switches',C,'count',('component', 'kind'),'Context switches'),
        MetricDefinition('runtime.fd.open',G,'count',('component',),'Open file descriptors/handles'),
        MetricDefinition('runtime.heartbeat.age',G,'seconds',('component',),'Age of last heartbeat'),
        MetricDefinition('runtime.loop.latency',H,'seconds',('component', 'loop'),'Main loop iteration latency'),
        MetricDefinition('runtime.threads',G,'count',('component',),'Thread count'),
    )
