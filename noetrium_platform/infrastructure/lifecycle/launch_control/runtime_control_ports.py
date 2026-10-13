from __future__ import annotations

from typing import Protocol

from .runtime_state_contracts import RuntimeControlState


class RuntimeControlTransactionPort(Protocol):
    """Minimal authoritative transaction surface required by exact runtime execution."""

    def exists(self) -> bool: ...

    def create(self, control_id: str, manifest_digest: str) -> RuntimeControlState: ...

    def read(self) -> RuntimeControlState: ...

    def write(self, state: RuntimeControlState) -> None: ...


class RuntimeControlRecoveryPort(Protocol):
    """History reconciliation surface required by one-click recovery orchestration."""

    def reconcile_history(self) -> bool: ...

    def assert_history_tail_matches(self, state: RuntimeControlState) -> None: ...


class RuntimeControlStorePort(RuntimeControlTransactionPort, RuntimeControlRecoveryPort, Protocol):
    """Full semantic store surface; concrete state/history backends remain hidden."""


__all__ = [
    "RuntimeControlRecoveryPort",
    "RuntimeControlStorePort",
    "RuntimeControlTransactionPort",
]
