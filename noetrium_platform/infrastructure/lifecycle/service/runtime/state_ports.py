from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol

from .service_state_contracts import ServiceSupervisorState


class ServiceStateStorePort(Protocol):
    """Disposable service-state projection boundary over causal lifecycle Events.

    Runtime controllers may read/write the typed projection and obtain an opaque
    evidence reference. Durable truth remains the underlying Event journal.
    """

    def exists(self) -> bool: ...

    def write(self, state: ServiceSupervisorState) -> None: ...

    def read(self) -> ServiceSupervisorState: ...

    def reference(self) -> str: ...

    def mutation(self) -> AbstractContextManager[object]:
        """Acquire the exact service-state mutation fence."""
        ...


__all__ = ["ServiceStateStorePort"]
