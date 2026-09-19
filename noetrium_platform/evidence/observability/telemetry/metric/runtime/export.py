from __future__ import annotations

from threading import Lock, RLock
import time

from noetrium_platform.evidence.observability.api.emission import (
    operational_observation_enabled,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext

from ..api.export import MetricExportBatch, MetricExporterPort, MetricExportReceipt
from ..api.rows import PendingMetric
from .registry import MetricRegistry


class BufferedMetricExportSink:
    """Validated, replay-safe operational export with retry-stable batches.

    This runtime owns only buffering and handoff mechanics. Metric semantics stay
    in MetricRegistry; the exporter owns only delivery mechanics. Rows are kept
    until an exporter acknowledges the exact deterministic batch identity.
    """

    def __init__(
        self,
        registry: MetricRegistry,
        exporter: MetricExporterPort,
        *,
        batch_size: int = 256,
    ) -> None:
        if not isinstance(registry, MetricRegistry):
            raise TypeError("registry must be MetricRegistry")
        if not callable(getattr(exporter, "export", None)):
            raise TypeError("exporter must implement export()")
        if not callable(getattr(exporter, "flush", None)):
            raise TypeError("exporter must implement flush()")
        if not callable(getattr(exporter, "close", None)):
            raise TypeError("exporter must implement close()")
        if type(batch_size) is not int or batch_size <= 0:
            raise ValueError("metric export batch_size must be positive")
        self.registry = registry
        self._exporter = exporter
        self._batch_size = batch_size
        self._pending: list[PendingMetric] = []
        self._lock = RLock()
        self._flush_lock = Lock()
        self._closing = False
        self._closed = False

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def prepare(
        self,
        context: ExecutionContext,
        name: str,
        value: float,
        **dimensions: str,
    ) -> PendingMetric:
        if not isinstance(context, ExecutionContext):
            raise TypeError("metric export context must be ExecutionContext")
        numeric = self.registry.validate_observation(name, value, dimensions)
        return PendingMetric(
            context=context,
            metric=name,
            value=numeric,
            timestamp=time.time(),
            dimensions=tuple(sorted(dimensions.items())),
        )

    def observe(
        self,
        context: ExecutionContext,
        name: str,
        value: float,
        **dimensions: str,
    ) -> str | None:
        if not operational_observation_enabled():
            return None
        row = self.prepare(context, name, value, **dimensions)
        with self._lock:
            if self._closing or self._closed:
                raise RuntimeError("metric export sink is closed")
            self._pending.append(row)
            should_flush = len(self._pending) >= self._batch_size
        if should_flush:
            receipts = self.flush()
            return None if not receipts else receipts[-1].batch_id
        return None

    def flush(self) -> tuple[MetricExportReceipt, ...]:
        receipts: list[MetricExportReceipt] = []
        with self._flush_lock:
            while True:
                with self._lock:
                    if self._closed:
                        return tuple(receipts)
                    if not self._pending:
                        break
                    rows = tuple(self._pending[: self._batch_size])
                batch = MetricExportBatch(rows)
                receipt = self._exporter.export(batch)
                if not isinstance(receipt, MetricExportReceipt):
                    raise TypeError("metric exporter must return MetricExportReceipt")
                if receipt.batch_id != batch.batch_id:
                    raise RuntimeError("metric exporter acknowledged the wrong batch identity")
                if receipt.accepted_count != len(rows):
                    raise RuntimeError("metric exporter did not acknowledge the complete batch")
                with self._lock:
                    if tuple(self._pending[: len(rows)]) != rows:
                        raise RuntimeError("metric export pending prefix changed during flush")
                    del self._pending[: len(rows)]
                receipts.append(receipt)
            self._exporter.flush()
        return tuple(receipts)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._closing:
                raise RuntimeError("metric export sink close already in progress")
            self._closing = True
        try:
            self.flush()
            self._exporter.close()
        except BaseException:
            with self._lock:
                self._closing = False
            raise
        with self._lock:
            self._closed = True
            self._closing = False

    def __enter__(self) -> "BufferedMetricExportSink":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.close()
        return False


__all__ = ["BufferedMetricExportSink"]
