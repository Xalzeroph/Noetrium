from __future__ import annotations

from typing import Any, Callable, Protocol, TypeAlias, TypeVar

from noetrium_platform.foundation.kernel.kernel import ExecutionContext

from .rows import PendingMetric


TelemetryStorageWriteRow: TypeAlias = tuple[
    str, float, float, str, str | None, str | None, str | None, str | None,
    str, str, str | None, str | None, str, str,
]
TelemetryStorageReadRow: TypeAlias = tuple[
    int, str, float, float, str, str | None, str | None, str, str,
    str | None, str | None, str, str,
]
T = TypeVar("T")


class TelemetryWriteActorPort(Protocol):
    @property
    def actor_id(self) -> str: ...

    def call(
        self,
        operation: str,
        fn: Callable[..., T],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> T: ...


class PendingMetricWriteSessionPort(Protocol):
    def insert_many(self, rows: tuple[PendingMetric, ...]) -> tuple[int, ...]: ...
    def close(self) -> None: ...


class TelemetryBatchStorePort(Protocol):
    def prepare(self, context: ExecutionContext, name: str, value: float, **dimensions: str) -> PendingMetric: ...
    def writer_session(self) -> PendingMetricWriteSessionPort: ...


class TelemetryPersistenceWriteSessionPort(Protocol):
    def insert_many(self, values: tuple[TelemetryStorageWriteRow, ...]) -> tuple[int, ...]: ...
    def close(self) -> None: ...


class TelemetryPersistencePort(Protocol):
    def insert_many(self, values: tuple[TelemetryStorageWriteRow, ...]) -> tuple[int, ...]: ...
    def writer_session(self) -> TelemetryPersistenceWriteSessionPort: ...
    def query(
        self,
        *,
        run_id: str,
        metric: str | None,
        decision_cycle_id: str | None,
        limit: int,
    ) -> tuple[TelemetryStorageReadRow, ...]: ...
    def count(self) -> int: ...


__all__ = [
    "PendingMetricWriteSessionPort",
    "TelemetryBatchStorePort",
    "TelemetryPersistencePort",
    "TelemetryPersistenceWriteSessionPort",
    "TelemetryStorageReadRow",
    "TelemetryStorageWriteRow",
    "TelemetryWriteActorPort",
]
