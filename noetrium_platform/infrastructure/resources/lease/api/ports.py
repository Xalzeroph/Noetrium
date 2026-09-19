from __future__ import annotations

from typing import Protocol

from .contracts import ResourceIdentity, ResourceLease, ResourceOwner


class ResourceOwnershipPort(Protocol):
    def register_owner(self, owner: ResourceOwner) -> None: ...
    def owner(self, resource: ResourceIdentity) -> ResourceOwner: ...
    def remove_owner(self, resource: ResourceIdentity) -> None: ...


class ResourceLeasePort(Protocol):
    def acquire(
        self,
        lease: ResourceLease,
        *,
        ttl_seconds: float | None = None,
        now: float | None = None,
    ) -> ResourceLease: ...
    def renew(
        self,
        lease_id: str,
        *,
        fencing_token: int,
        ttl_seconds: float,
        now: float | None = None,
    ) -> ResourceLease: ...
    def release(self, lease_id: str, *, now: float | None = None) -> ResourceLease: ...
    def get(self, lease_id: str, *, now: float | None = None) -> ResourceLease: ...
    def active_for(
        self, resource: ResourceIdentity, *, now: float | None = None
    ) -> tuple[ResourceLease, ...]: ...
    def history_for(
        self, resource: ResourceIdentity, *, now: float | None = None
    ) -> tuple[ResourceLease, ...]: ...
    def reconcile_expired(self, *, now: float | None = None) -> tuple[ResourceLease, ...]: ...


__all__ = ["ResourceLeasePort", "ResourceOwnershipPort"]
