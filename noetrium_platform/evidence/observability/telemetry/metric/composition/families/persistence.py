from __future__ import annotations

from noetrium_platform.evidence.observability.telemetry.metric.api import MetricDefinition, MetricKind


def definitions() -> tuple[MetricDefinition, ...]:
    C=MetricKind.COUNTER; G=MetricKind.GAUGE; H=MetricKind.HISTOGRAM
    return (
        MetricDefinition('checkpoint.bytes',H,'bytes',('kind',),'Checkpoint bytes'),
        MetricDefinition('checkpoint.delta.bytes',H,'bytes',('kind',),'Incremental checkpoint bytes'),
        MetricDefinition('checkpoint.duration',H,'seconds',('kind', 'result'),'Checkpoint create/verify duration'),
        MetricDefinition('journal.append.latency',H,'seconds',('journal',),'Append-only journal write latency'),
        MetricDefinition('journal.bytes',G,'bytes',('journal',),'Journal storage bytes'),
        MetricDefinition('journal.verify.latency',H,'seconds',('journal', 'result'),'Journal verification latency'),
        MetricDefinition('sqlite.busy',C,'count',('database', 'operation'),'SQLite busy/lock events'),
        MetricDefinition('sqlite.commit.latency',H,'seconds',('database', 'operation'),'SQLite commit latency'),
        MetricDefinition('sqlite.wal.bytes',G,'bytes',('database',),'SQLite WAL size'),
    )
