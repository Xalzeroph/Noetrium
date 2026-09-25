from __future__ import annotations

from typing import Protocol

from .lease import RecoveryLease


class RecoveryLeaseReadPort(Protocol):
    """Read-only view of durable recovery ownership."""

    def read(self) -> RecoveryLease | None: ...


class RecoveryLeaseStatusPort(RecoveryLeaseReadPort, Protocol):
    """Read-only recovery state plus backend-owned diagnostic evidence references."""

    def evidence_refs(self) -> tuple[str, ...]: ...


class RecoveryLeaseStatePort(RecoveryLeaseReadPort, Protocol):
    """Durable recovery ownership state; contains no execution-fencing semantics."""

    def acquire(
        self,
        owner_id: str,
        manifest_digest: str,
        *,
        ttl_seconds: float = 300.0,
        now: float | None = None,
    ) -> RecoveryLease: ...

    def renew(
        self,
        owner_id: str,
        manifest_digest: str,
        *,
        ttl_seconds: float = 300.0,
        now: float | None = None,
    ) -> RecoveryLease: ...

    def assert_owned(
        self,
        owner_id: str,
        manifest_digest: str,
        *,
        now: float | None = None,
    ) -> RecoveryLease: ...

    def release(self, owner_id: str, manifest_digest: str) -> None: ...


class RecoveryExecutionPort(Protocol):
    """Long-lived fence for one recovery command; storage implementation is opaque."""

    def __enter__(self) -> "RecoveryExecutionPort": ...
    def __exit__(self, exc_type, exc, tb) -> None: ...
    def renew(self) -> RecoveryLease: ...
    def assert_owned(self) -> RecoveryLease: ...


class RecoveryExecutionFactoryPort(Protocol):
    def execution(
        self,
        owner_id: str,
        manifest_digest: str,
        *,
        ttl_seconds: float,
    ) -> RecoveryExecutionPort: ...


__all__ = [
    "RecoveryExecutionFactoryPort",
    "RecoveryExecutionPort",
    "RecoveryLeaseReadPort",
    "RecoveryLeaseStatePort",
    "RecoveryLeaseStatusPort",
]
