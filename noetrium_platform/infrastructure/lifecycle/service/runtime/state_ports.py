from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol

from .service_state_contracts import ServiceSupervisorState


class ServiceStateStorePort(Protocol):
    """Authoritative service-state persistence boundary.

    Runtime authorities may ask whether state exists, read/write the typed state,
    and obtain an opaque evidence reference.  They never inspect filesystem paths.
    """

    def exists(self) -> bool: ...

    def write(self, state: ServiceSupervisorState) -> None: ...

    def read(self) -> ServiceSupervisorState: ...

    def reference(self) -> str: ...

    def mutation(self) -> AbstractContextManager[object]:
        """Acquire the exact service-state mutation fence."""
        ...


__all__ = ["ServiceStateStorePort"]
