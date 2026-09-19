from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from noetrium_platform.evidence.observability.api import replay_observation_scope
from noetrium_platform.evidence.observability.telemetry.metric.api import (
    MetricDefinition,
    MetricExportBatch,
    MetricExportReceipt,
    MetricKind,
)
from noetrium_platform.evidence.observability.telemetry.metric.runtime import (
    BufferedMetricExportSink,
    MetricRegistry,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext


def _registry() -> MetricRegistry:
    registry = MetricRegistry()
    registry.register(
        MetricDefinition(
            "test.requests",
            MetricKind.COUNTER,
            "count",
            ("role",),
            "request count",
        )
    )
    return registry


def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id="run-1",
        trace_id="trace-1",
        span_id="span-1",
        task_id="task-1",
    )


@dataclass
class _Exporter:
    fail_first: bool = False
    wrong_receipt: bool = False
    attempts: list[MetricExportBatch] = field(default_factory=list)
    flushed: int = 0
    closed: bool = False

    def export(self, batch: MetricExportBatch) -> MetricExportReceipt:
        self.attempts.append(batch)
        if self.fail_first and len(self.attempts) == 1:
            raise RuntimeError("synthetic export failure")
        if self.wrong_receipt:
            return MetricExportReceipt("0" * 64, len(batch.rows))
        return MetricExportReceipt(batch.batch_id, len(batch.rows))

    def flush(self) -> None:
        self.flushed += 1

    def close(self) -> None:
        self.closed = True


def test_telemetry_metric_export_batches_validated_rows_with_stable_identity() -> None:
    exporter = _Exporter()
    sink = BufferedMetricExportSink(_registry(), exporter, batch_size=2)

    assert sink.observe(_context(), "test.requests", 1, role="planner") is None
    batch_id = sink.observe(_context(), "test.requests", 2, role="planner")

    assert batch_id is not None
    assert len(exporter.attempts) == 1
    assert exporter.attempts[0].batch_id == batch_id
    assert tuple(row.value for row in exporter.attempts[0].rows) == (1.0, 2.0)
    assert exporter.attempts[0].rows[0].dimensions == (("role", "planner"),)
    assert sink.pending_count == 0


def test_telemetry_metric_export_retries_the_same_batch_after_failure() -> None:
    exporter = _Exporter(fail_first=True)
    sink = BufferedMetricExportSink(_registry(), exporter, batch_size=2)

    sink.observe(_context(), "test.requests", 1, role="planner")
    with pytest.raises(RuntimeError, match="synthetic export failure"):
        sink.observe(_context(), "test.requests", 1, role="planner")

    assert sink.pending_count == 2
    failed_batch_id = exporter.attempts[0].batch_id

    receipts = sink.flush()

    assert receipts[0].batch_id == failed_batch_id
    assert exporter.attempts[1].batch_id == failed_batch_id
    assert sink.pending_count == 0


def test_telemetry_metric_export_rejects_mismatched_ack_without_dropping_rows() -> None:
    exporter = _Exporter(wrong_receipt=True)
    sink = BufferedMetricExportSink(_registry(), exporter, batch_size=1)

    with pytest.raises(RuntimeError, match="wrong batch identity"):
        sink.observe(_context(), "test.requests", 1, role="planner")

    assert sink.pending_count == 1


def test_telemetry_metric_export_is_replay_safe() -> None:
    exporter = _Exporter()
    sink = BufferedMetricExportSink(_registry(), exporter, batch_size=1)

    with replay_observation_scope():
        assert sink.observe(_context(), "test.requests", 1, role="planner") is None

    assert exporter.attempts == []
    assert sink.pending_count == 0


def test_telemetry_metric_export_close_flushes_pending_rows_and_closes_exporter() -> None:
    exporter = _Exporter()
    sink = BufferedMetricExportSink(_registry(), exporter, batch_size=8)

    sink.observe(_context(), "test.requests", 1, role="planner")
    sink.close()

    assert len(exporter.attempts) == 1
    assert exporter.flushed == 1
    assert exporter.closed is True
    assert sink.pending_count == 0
    with pytest.raises(RuntimeError, match="closed"):
        sink.observe(_context(), "test.requests", 1, role="planner")
