from __future__ import annotations

from typing import Protocol

from .runtime_state_contracts import RuntimeControlState


class RuntimeControlStateReadPort(Protocol):
    """Read-only projection over causal runtime-state Event truth."""

    def exists(self) -> bool: ...

    def read(self) -> RuntimeControlState: ...

    def reference(self) -> str: ...


class RuntimeControlStateStorePort(RuntimeControlStateReadPort, Protocol):
    """Writable causal runtime-state boundary with disposable latest projection."""

    def write(self, state: RuntimeControlState) -> None: ...


__all__ = ["RuntimeControlStateReadPort", "RuntimeControlStateStorePort"]
