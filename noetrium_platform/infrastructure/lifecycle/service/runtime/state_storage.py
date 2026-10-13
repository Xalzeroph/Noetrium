from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.file_lock import (
    InterprocessFileLock,
)
from noetrium_platform.foundation.kernel.event_store import (
    FileCausalEventStore,
)

from .service_state_codec import (
    ServiceStateIntegrityError,
    ServiceSupervisorStateCodec,
)
from .service_state_contracts import ServiceSupervisorState


class FileServiceStateStore:
    """Disposable service-state projection backed by causal Event Units."""

    def __init__(self, path: Path, codec: ServiceSupervisorStateCodec | None = None) -> None:
        self._path = path
        self._codec = codec or ServiceSupervisorStateCodec()
        self._journal = FileCausalEventStore(
            path,
            state_schema="service.supervisor-state.v1",
        )

    @staticmethod
    def _integrity_error(exc: RuntimeError) -> ServiceStateIntegrityError:
        return ServiceStateIntegrityError(
            "service state causal authority integrity failure"
        )

    def exists(self) -> bool:
        try:
            return self._journal.exists()
        except RuntimeError as exc:
            raise self._integrity_error(exc) from exc

    def write(self, state: ServiceSupervisorState) -> None:
        payload = self._codec.encode(state)
        try:
            self._journal.append(payload, phase="service-state")
        except RuntimeError as exc:
            raise self._integrity_error(exc) from exc

    def read(self) -> ServiceSupervisorState:
        try:
            payload = self._journal.read()
        except RuntimeError as exc:
            raise self._integrity_error(exc) from exc
        return self._codec.decode(payload)

    def reference(self) -> str:
        return str(self._path)

    def mutation(self) -> InterprocessFileLock:
        return InterprocessFileLock(
            self._path.with_name(self._path.name + ".mutation.lock")
        )

    def verify_projection_rebuild(self) -> ServiceSupervisorState | None:
        try:
            payload = self._journal.verify_projection_rebuild()
        except RuntimeError as exc:
            raise self._integrity_error(exc) from exc
        return None if not payload else self._codec.decode(payload)


__all__ = ["FileServiceStateStore"]
