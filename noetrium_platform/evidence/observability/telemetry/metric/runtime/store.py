from __future__ import annotations

import time

from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.evidence.observability.api.emission import operational_observation_enabled

from ..api.rows import PendingMetric
from .codec import decode_metric_query_row, encode_pending_metric
from .registry import MetricRegistry
from ..api.ports import TelemetryPersistencePort, TelemetryPersistenceWriteSessionPort


class TelemetryStore:
    """Metric validation/domain facade over an injected persistence backend."""

    def __init__(self, registry: MetricRegistry, backend: TelemetryPersistencePort) -> None:
        self.registry = registry
        self._backend = backend

    def prepare(self, context: ExecutionContext, name: str, value: float, **dimensions: str) -> PendingMetric:
        return PendingMetric(
            context,
            name,
            self.registry.validate_observation(name, value, dimensions),
            time.time(),
            tuple(sorted(dimensions.items())),
        )

    def insert_many(self, rows: tuple[PendingMetric, ...]) -> tuple[int, ...]:
        return self._backend.insert_many(tuple(encode_pending_metric(row) for row in rows))

    def writer_session(self) -> "TelemetryStoreWriteSession":
        return TelemetryStoreWriteSession(self._backend.writer_session())

    def observe(self, context: ExecutionContext, name: str, value: float, **dimensions: str) -> int:
        if not operational_observation_enabled():
            return 0
        return self.insert_many((self.prepare(context, name, value, **dimensions),))[0]

    def query(
        self,
        *,
        run_id: str,
        metric: str | None = None,
        decision_cycle_id: str | None = None,
        limit: int = 1000,
    ) -> tuple[dict[str, object], ...]:
        if limit <= 0:
            return ()
        rows = self._backend.query(
            run_id=run_id,
            metric=metric,
            decision_cycle_id=decision_cycle_id,
            limit=limit,
        )
        return tuple(decode_metric_query_row(row) for row in rows)

    def count(self) -> int:
        return self._backend.count()


class TelemetryStoreWriteSession:
    """Domain writer session that owns metric encoding, not backend internals."""

    def __init__(self, backend_session: TelemetryPersistenceWriteSessionPort) -> None:
        self._backend_session = backend_session

    def insert_many(self, rows: tuple[PendingMetric, ...]) -> tuple[int, ...]:
        return self._backend_session.insert_many(tuple(encode_pending_metric(row) for row in rows))

    def close(self) -> None:
        self._backend_session.close()

    def __enter__(self) -> "TelemetryStoreWriteSession":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


__all__ = ["TelemetryStore", "TelemetryStoreWriteSession"]
