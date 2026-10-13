from __future__ import annotations

from typing import Mapping, Protocol

from noetrium_platform.foundation.kernel.kernel import ExecutionContext, JsonObject

from .contracts import RecordCapture, RawObservationReceipt, RawObservationSchema


class RawObservationSinkPort(Protocol):
    def capture(self, envelope: RecordCapture) -> RawObservationReceipt: ...


class RawObservationPersistencePort(Protocol):
    def append(
        self,
        context: ExecutionContext,
        schema: RawObservationSchema,
        payload: JsonObject,
        *,
        timestamp: float | None,
        idempotency_key: str | None,
    ) -> RawObservationReceipt: ...

    def append_many(
        self,
        records: tuple[tuple[
            ExecutionContext, RawObservationSchema, JsonObject,
            float | None, str | None,
        ], ...],
    ) -> tuple[RawObservationReceipt, ...]: ...

    def verify(self, run_id: str, family: str) -> tuple[str, ...]: ...

    def read(self, run_id: str, family: str, *, limit: int = 10000) -> tuple[JsonObject, ...]: ...

    def release_run(self, run_id: str) -> None: ...

    def close(self) -> None: ...


__all__ = ["RawObservationPersistencePort", "RawObservationSinkPort"]
