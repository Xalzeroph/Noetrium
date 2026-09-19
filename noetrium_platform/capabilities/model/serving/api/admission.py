from __future__ import annotations

from typing import Protocol

from noetrium_platform.foundation.kernel.concurrency.api import CancellationTokenPort


class ModelAdmissionTimeout(TimeoutError):
    pass


class ModelAdmissionClosed(RuntimeError):
    pass


class ModelAdmissionLeasePort(Protocol):
    def release(self) -> None: ...


class ModelAdmissionPort(Protocol):
    def acquire(
        self,
        timeout_seconds: float | None = None,
        *,
        cancellation: CancellationTokenPort | None = None,
        owner_id: str | None = None,
    ) -> ModelAdmissionLeasePort: ...


class ModelAdmissionRegistryPort(Protocol):
    def controller_for(
        self,
        *,
        deployment_id: str,
        deployment_generation: str,
        qualified_capacity: int,
    ) -> ModelAdmissionPort: ...

    def close(self) -> None: ...


__all__ = [
    "ModelAdmissionClosed",
    "ModelAdmissionLeasePort",
    "ModelAdmissionPort",
    "ModelAdmissionRegistryPort",
    "ModelAdmissionTimeout",
]
