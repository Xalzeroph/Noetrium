from __future__ import annotations

import math
from pathlib import Path
from time import time

from noetrium_platform.infrastructure.resources.lease.api import (
    ResourceIdentity,
    ResourceLease,
    ResourceOwner,
    ResourceLeasePort,
    ResourceOwnershipConflict,
    ResourceOwnershipPort,
)
from noetrium_platform.infrastructure.resources.providers.sqlite_connection import durable_sqlite_connection
from noetrium_platform.infrastructure.resources.providers.sqlite_lease_ops import (
    acquire_resource_lease,
    decode_resource_lease,
    decode_resource_owner,
    ensure_resource_owner,
    reconcile_expired_resource_leases,
    release_resource_lease,
    renew_resource_lease,
)
from noetrium_platform.infrastructure.resources.providers.sqlite_resource import (
    RESOURCE_SCHEMA_VERSION,
    ensure_resource_schema,
    expire_lease,
    expire_resource,
)


class SQLiteResourceLeaseRegistry(ResourceOwnershipPort, ResourceLeasePort):
    """Durable owner/lease authority with TTL, renewal and monotonic fencing.

    Point operations expire only the addressed lease/resource. Global expiry is
    reserved for explicit reconciliation, avoiding hidden O(total leases) work
    in acquire/get/release hot paths.
    """

    SCHEMA_VERSION = RESOURCE_SCHEMA_VERSION

    def __init__(self, path: str | Path, *, timeout_seconds: float = 30.0) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not math.isfinite(float(timeout_seconds)) or timeout_seconds <= 0:
            raise ValueError("SQLite resource timeout_seconds must be finite and positive")
        self.timeout_seconds = float(timeout_seconds)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                ensure_resource_schema(conn)
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def _connection(self):
        return durable_sqlite_connection(self.path, timeout_seconds=self.timeout_seconds)

    def register_owner(self, owner: ResourceOwner) -> None:
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                ensure_resource_owner(conn, owner)
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def owner(self, resource: ResourceIdentity) -> ResourceOwner:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM resource_owners WHERE resource_key=?", (resource.key,)).fetchone()
        if row is None:
            raise KeyError(resource.key)
        return decode_resource_owner(row)

    def remove_owner(self, resource: ResourceIdentity) -> None:
        now_epoch_s = time()
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            expire_resource(conn, resource.key, now_epoch_s)
            active = conn.execute(
                "SELECT 1 FROM resource_leases WHERE resource_key=? AND state='active'", (resource.key,)
            ).fetchone()
            if active is not None:
                conn.rollback()
                raise ResourceOwnershipConflict(f"resource has active leases: {resource.key}")
            conn.execute("DELETE FROM resource_owners WHERE resource_key=?", (resource.key,))
            conn.commit()

    def acquire(
        self,
        lease: ResourceLease,
        *,
        ttl_seconds: float | None = None,
        now: float | None = None,
    ) -> ResourceLease:
        now_epoch_s = time() if now is None else float(now)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                granted = acquire_resource_lease(
                    conn, lease, ttl_seconds=ttl_seconds, now_epoch_s=now_epoch_s
                )
                conn.commit()
                return granted
            except BaseException:
                conn.rollback()
                raise

    def renew(
        self,
        lease_id: str,
        *,
        fencing_token: int,
        ttl_seconds: float,
        now: float | None = None,
    ) -> ResourceLease:
        now_epoch_s = time() if now is None else float(now)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                renewed = renew_resource_lease(
                    conn,
                    lease_id,
                    fencing_token=fencing_token,
                    ttl_seconds=ttl_seconds,
                    now_epoch_s=now_epoch_s,
                )
                conn.commit()
                return renewed
            except BaseException:
                conn.rollback()
                raise

    def release(self, lease_id: str, *, now: float | None = None) -> ResourceLease:
        now_epoch_s = time() if now is None else float(now)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                released = release_resource_lease(
                    conn, lease_id, now_epoch_s=now_epoch_s
                )
                conn.commit()
                return released
            except BaseException:
                conn.rollback()
                raise

    def get(self, lease_id: str, *, now: float | None = None) -> ResourceLease:
        now_epoch_s = time() if now is None else float(now)
        if not math.isfinite(now_epoch_s):
            raise ValueError("lease observation time must be finite")
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM resource_leases WHERE lease_id=?", (lease_id,)).fetchone()
        if row is None:
            raise KeyError(lease_id)
        current = decode_resource_lease(row)
        if not current.expired_at(now_epoch_s):
            return current
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            expire_lease(conn, lease_id, now_epoch_s)
            row = conn.execute("SELECT * FROM resource_leases WHERE lease_id=?", (lease_id,)).fetchone()
            conn.commit()
        if row is None:
            raise KeyError(lease_id)
        return decode_resource_lease(row)

    def active_for(
        self, resource: ResourceIdentity, *, now: float | None = None
    ) -> tuple[ResourceLease, ...]:
        now_epoch_s = time() if now is None else float(now)
        if not math.isfinite(now_epoch_s):
            raise ValueError("lease observation time must be finite")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            expire_resource(conn, resource.key, now_epoch_s)
            rows = conn.execute(
                "SELECT * FROM resource_leases WHERE resource_key=? AND state='active' ORDER BY lease_id",
                (resource.key,),
            ).fetchall()
            conn.commit()
        return tuple(decode_resource_lease(row) for row in rows)

    def history_for(
        self, resource: ResourceIdentity, *, now: float | None = None
    ) -> tuple[ResourceLease, ...]:
        now_epoch_s = time() if now is None else float(now)
        if not math.isfinite(now_epoch_s):
            raise ValueError("lease observation time must be finite")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            expire_resource(conn, resource.key, now_epoch_s)
            rows = conn.execute(
                "SELECT * FROM resource_leases WHERE resource_key=? "
                "ORDER BY fencing_token, lease_id",
                (resource.key,),
            ).fetchall()
            conn.commit()
        return tuple(decode_resource_lease(row) for row in rows)

    def reconcile_expired(self, *, now: float | None = None) -> tuple[ResourceLease, ...]:
        now_epoch_s = time() if now is None else float(now)
        if not math.isfinite(now_epoch_s):
            raise ValueError("lease observation time must be finite")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                rows = reconcile_expired_resource_leases(
                    conn, now_epoch_s=now_epoch_s
                )
                conn.commit()
                return rows
            except BaseException:
                conn.rollback()
                raise


__all__ = ["SQLiteResourceLeaseRegistry"]
