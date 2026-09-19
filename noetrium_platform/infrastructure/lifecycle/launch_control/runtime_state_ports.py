from __future__ import annotations

from typing import Protocol

from .runtime_state_contracts import RuntimeControlState


class RuntimeControlStateReadPort(Protocol):
    """Read-only authoritative runtime-state boundary."""

    def exists(self) -> bool: ...

    def read(self) -> RuntimeControlState: ...

    def reference(self) -> str: ...


class RuntimeControlStateStorePort(RuntimeControlStateReadPort, Protocol):
    """Writable authoritative runtime-state boundary."""

    def write(self, state: RuntimeControlState) -> None: ...


__all__ = ["RuntimeControlStateReadPort", "RuntimeControlStateStorePort"]
