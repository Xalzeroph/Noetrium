from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from noetrium_platform.foundation.kernel.concurrency.api import CancellationTokenPort


class ModelAdmissionTimeout(TimeoutError):
    pass


class ModelAdmissionClosed(RuntimeError):
    pass


class ModelAdmissionLeasePort(Protocol):
    @property
    def claim_id(self) -> str: ...
    def release(self) -> None: ...


class ModelAdmissionPort(Protocol):
    @property
    def capacity(self) -> int: ...

    @property
    def contention_recheck_seconds(self) -> float: ...

    def subscribe_capacity_change(
        self, callback: Callable[[], None],
    ) -> Callable[[], None] | None: ...

    def qualify_continuity(self, capacity: int) -> None: ...

    def try_reserve_continuity(
        self, *, owner_id: str, flow_id: str,
    ) -> ModelAdmissionLeasePort | None: ...

    def acquire(
        self,
        timeout_seconds: float | None = None,
        *,
        cancellation: CancellationTokenPort | None = None,
        owner_id: str | None = None,
        continuity_claim_id: str | None = None,
    ) -> ModelAdmissionLeasePort: ...


class ModelAdmissionRegistryPort(Protocol):
    def controller_for(
        self,
        *,
        deployment_id: str,
        deployment_generation: str,
        qualified_capacity: int,
        continuity_capacity: int | None = None,
    ) -> ModelAdmissionPort: ...

    def close(self) -> None: ...


__all__ = [
    "ModelAdmissionClosed",
    "ModelAdmissionLeasePort",
    "ModelAdmissionPort",
    "ModelAdmissionRegistryPort",
    "ModelAdmissionTimeout",
]
