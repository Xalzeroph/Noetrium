from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol

from .runtime_history_contracts import RuntimeHistoryEntry, RuntimeHistoryProjectionKind
from .runtime_state_contracts import RuntimeControlState


class RuntimeHistoryAppendSession(Protocol):
    """One verified, exclusively-held append opportunity against a fixed history tail."""

    @property
    def tail(self) -> RuntimeHistoryEntry | None: ...

    def append(
        self,
        state: RuntimeControlState,
        *,
        projection_kind: RuntimeHistoryProjectionKind = RuntimeHistoryProjectionKind.STATE_PROJECTION_WRITE,
    ) -> RuntimeHistoryEntry: ...


class RuntimeHistoryReadPort(Protocol):
    """Read-only integrity/projection boundary for runtime history."""

    def verify(self) -> tuple[str, ...]: ...

    def assert_tail_matches(self, state: RuntimeControlState) -> None: ...

    def reference(self) -> str: ...


class RuntimeHistoryPort(RuntimeHistoryReadPort, Protocol):
    """Mutable diagnostic projection boundary; it owns no runtime truth."""

    def assert_integrity(self) -> None: ...

    def verified_append_session(self) -> AbstractContextManager[RuntimeHistoryAppendSession]: ...

    def append(
        self,
        state: RuntimeControlState,
        *,
        projection_kind: RuntimeHistoryProjectionKind = RuntimeHistoryProjectionKind.STATE_PROJECTION_WRITE,
    ) -> RuntimeHistoryEntry: ...

    def reconcile_projection(self, state: RuntimeControlState) -> bool: ...


class RuntimeHistoryStoragePort(Protocol):
    """Opaque durable row storage. It owns no hash-chain or reconciliation semantics."""

    def lines(self) -> tuple[str, ...]: ...

    def append(self, encoded_row: bytes) -> None: ...

    def reference(self) -> str: ...

    def exclusive(self) -> AbstractContextManager[object]: ...


__all__ = [
    "RuntimeHistoryAppendSession",
    "RuntimeHistoryPort",
    "RuntimeHistoryReadPort",
    "RuntimeHistoryStoragePort",
]
