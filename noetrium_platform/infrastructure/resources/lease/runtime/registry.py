from __future__ import annotations

import math
from pathlib import Path

from noetrium_platform.infrastructure.resources.lease.api import (
    LeaseClockPort,
    ResourceIdentity,
    ResourceKind,
    ResourceLease,
    ResourceOwner,
    ResourceLeasePort,
    ResourceOwnershipConflict,
    ResourceOwnershipPort,
)
from noetrium_platform.foundation.kernel.kernel.durability.sqlite import (
    durable_sqlite_connection,
    immediate_sqlite_transaction,
)
from .operations import (
    acquire_resource_lease,
    decode_resource_lease,
    decode_resource_owner,
    ensure_resource_owner,
    reconcile_expired_resource_leases,
    release_resource_lease,
    renew_resource_lease,
)
from noetrium_platform.infrastructure.resources.sqlite_resource import (
    RESOURCE_SCHEMA_VERSION,
    authoritative_lease_now,
    ensure_resource_schema,
    expire_lease,
    expire_resource,
)
class ResourceLeaseRegistry(ResourceOwnershipPort, ResourceLeasePort):
    """Sole durable resource owner/lease authority with TTL and monotonic fencing.

    Point operations expire only the addressed lease/resource. Global expiry is
    reserved for explicit reconciliation, avoiding hidden O(total leases) work
    in acquire/get/release hot paths.
    """

    SCHEMA_VERSION = RESOURCE_SCHEMA_VERSION

    def __init__(
        self,
        path: str | Path,
        *,
        timeout_seconds: float = 30.0,
        clock: LeaseClockPort | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not math.isfinite(float(timeout_seconds)) or timeout_seconds <= 0:
            raise ValueError("resource authority timeout_seconds must be finite and positive")
        self.timeout_seconds = float(timeout_seconds)
        from .clock import LocalLeaseClock

        self._clock = LocalLeaseClock() if clock is None else clock
        if not isinstance(self._clock, LeaseClockPort):
            raise TypeError("resource authority requires LeaseClockPort")
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource schema",
            ):
                ensure_resource_schema(conn)

    def _connection(self):
        return durable_sqlite_connection(
            self.path,
            timeout_seconds=self.timeout_seconds,
        )

    def _authority_now(self, conn, explicit_now: float | None) -> float:
        if explicit_now is not None:
            value = float(explicit_now)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(
                    "lease observation time must be finite and positive"
                )
        return authoritative_lease_now(conn, self._clock.read())

    def register_owner(self, owner: ResourceOwner) -> None:
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource owner",
            ):
                ensure_resource_owner(conn, owner)

    def owner(self, resource: ResourceIdentity) -> ResourceOwner:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM resource_owners WHERE resource_key=?", (resource.key,)).fetchone()
        if row is None:
            raise KeyError(resource.key)
        return decode_resource_owner(row)

    def remove_owner(self, resource: ResourceIdentity) -> None:
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource owner removal",
            ):
                now_epoch_s = self._authority_now(conn, None)
                expire_resource(conn, resource.key, now_epoch_s)
                active = conn.execute(
                    "SELECT 1 FROM resource_leases WHERE resource_key=? AND state='active'", (resource.key,)
                ).fetchone()
                if active is not None:
                    raise ResourceOwnershipConflict(f"resource has active leases: {resource.key}")
                conn.execute("DELETE FROM resource_owners WHERE resource_key=?", (resource.key,))

    def acquire(
        self,
        lease: ResourceLease,
        *,
        ttl_seconds: float | None = None,
        now: float | None = None,
    ) -> ResourceLease:
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource lease acquire",
            ):
                now_epoch_s = self._authority_now(conn, now)
                return acquire_resource_lease(
                    conn, lease, ttl_seconds=ttl_seconds, now_epoch_s=now_epoch_s
                )

    def renew(
        self,
        lease_id: str,
        *,
        fencing_token: int,
        ttl_seconds: float,
        now: float | None = None,
    ) -> ResourceLease:
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource lease renew",
            ):
                now_epoch_s = self._authority_now(conn, now)
                return renew_resource_lease(
                    conn,
                    lease_id,
                    fencing_token=fencing_token,
                    ttl_seconds=ttl_seconds,
                    now_epoch_s=now_epoch_s,
                )

    def release(
        self,
        lease_id: str,
        *,
        fencing_token: int,
        now: float | None = None,
    ) -> ResourceLease:
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource lease release",
            ):
                now_epoch_s = self._authority_now(conn, now)
                return release_resource_lease(
                    conn,
                    lease_id,
                    fencing_token=fencing_token,
                    now_epoch_s=now_epoch_s,
                )

    def get(self, lease_id: str, *, now: float | None = None) -> ResourceLease:
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource lease expiry",
            ):
                now_epoch_s = self._authority_now(conn, now)
                expire_lease(conn, lease_id, now_epoch_s)
                row = conn.execute(
                    "SELECT * FROM resource_leases WHERE lease_id=?",
                    (lease_id,),
                ).fetchone()
        if row is None:
            raise KeyError(lease_id)
        return decode_resource_lease(row)

    def active_for(
        self, resource: ResourceIdentity, *, now: float | None = None
    ) -> tuple[ResourceLease, ...]:
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource active leases",
            ):
                now_epoch_s = self._authority_now(conn, now)
                expire_resource(conn, resource.key, now_epoch_s)
                rows = conn.execute(
                    "SELECT * FROM resource_leases WHERE resource_key=? AND state='active' ORDER BY lease_id",
                    (resource.key,),
                ).fetchall()
        return tuple(decode_resource_lease(row) for row in rows)

    def active_leases(
        self,
        *,
        resource_kind: ResourceKind | None = None,
        now: float | None = None,
    ) -> tuple[ResourceLease, ...]:
        if resource_kind is not None and type(resource_kind) is not ResourceKind:
            raise TypeError("resource_kind must be ResourceKind when provided")
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource active lease enumeration",
            ):
                now_epoch_s = self._authority_now(conn, now)
                reconcile_expired_resource_leases(
                    conn,
                    now_epoch_s=now_epoch_s,
                    resource_kind=resource_kind,
                )
                if resource_kind is None:
                    rows = conn.execute(
                        "SELECT * FROM resource_leases "
                        "WHERE state='active' ORDER BY lease_id"
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM resource_leases "
                        "WHERE state='active' AND resource_kind=? "
                        "ORDER BY lease_id",
                        (resource_kind.value,),
                    ).fetchall()
        return tuple(decode_resource_lease(row) for row in rows)

    def history_for(
        self, resource: ResourceIdentity, *, now: float | None = None
    ) -> tuple[ResourceLease, ...]:
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource lease history",
            ):
                now_epoch_s = self._authority_now(conn, now)
                expire_resource(conn, resource.key, now_epoch_s)
                rows = conn.execute(
                    "SELECT * FROM resource_leases WHERE resource_key=? "
                    "ORDER BY fencing_token, lease_id",
                    (resource.key,),
                ).fetchall()
        return tuple(decode_resource_lease(row) for row in rows)

    def reconcile_expired(
        self,
        *,
        now: float | None = None,
        resource_kind: ResourceKind | None = None,
    ) -> tuple[ResourceLease, ...]:
        if resource_kind is not None and type(resource_kind) is not ResourceKind:
            raise TypeError("resource_kind must be ResourceKind when provided")
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource lease reconciliation",
            ):
                now_epoch_s = self._authority_now(conn, now)
                return reconcile_expired_resource_leases(
                    conn,
                    now_epoch_s=now_epoch_s,
                    resource_kind=resource_kind,
                )


__all__ = ["ResourceLeaseRegistry"]
