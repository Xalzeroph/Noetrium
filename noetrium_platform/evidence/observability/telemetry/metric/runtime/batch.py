from __future__ import annotations

from threading import RLock

from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.evidence.observability.api.emission import operational_observation_enabled

from ..api.rows import PendingMetric
from ..api.ports import PendingMetricWriteSessionPort, TelemetryBatchStorePort


class TelemetryBatchRecorder:
    """Hot-path recorder with one reusable writer session per recorder lifecycle."""

    def __init__(self, store: TelemetryBatchStorePort, batch_size: int = 128) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self.store = store
        self.batch_size = batch_size
        self._pending: list[PendingMetric] = []
        self._lock = RLock()
        self._closed = False
        self._session: PendingMetricWriteSessionPort | None = store.writer_session()

    def observe(self, context: ExecutionContext, name: str, value: float, **dimensions: str) -> None:
        if not operational_observation_enabled():
            return
        row = self.store.prepare(context, name, value, **dimensions)
        with self._lock:
            if self._closed:
                raise RuntimeError("telemetry recorder is closed")
            self._pending.append(row)
            if len(self._pending) >= self.batch_size:
                self._flush_locked()

    def _flush_locked(self) -> tuple[int, ...]:
        batch = tuple(self._pending)
        if not batch:
            return ()
        if self._session is None:
            self._session = self.store.writer_session()
        session = self._session
        try:
            ids = session.insert_many(batch)
        except BaseException as primary:
            # A failed commit must retain the batch, and cleanup failure must
            # never replace the commit failure that caused recovery. Detach the
            # failed session before cleanup so the next flush can always reopen.
            self._session = None
            try:
                session.close()
            except BaseException as close_exc:
                primary.add_note(
                    "telemetry writer session cleanup failed: "
                    f"{type(close_exc).__name__}"
                )
            raise
        del self._pending[:len(batch)]
        return ids

    def flush(self) -> tuple[int, ...]:
        with self._lock:
            if self._closed:
                return ()
            return self._flush_locked()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._flush_locked()
            session = self._session
            if session is not None:
                # Keep the session reachable until cleanup succeeds so a
                # transient close failure can be retried by this recorder.
                session.close()
            self._session = None
            self._closed = True

    @property
    def buffered(self) -> int:
        with self._lock:
            return len(self._pending)

    def __enter__(self) -> "TelemetryBatchRecorder":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> None:
        del exc_type, tb
        try:
            self.close()
        except BaseException as close_exc:
            if exc is None:
                raise
            exc.add_note(
                f"telemetry recorder close failed: {type(close_exc).__name__}"
            )


__all__ = ["TelemetryBatchRecorder"]
