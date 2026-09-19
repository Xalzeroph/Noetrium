from __future__ import annotations

import math
import sqlite3
from dataclasses import replace

from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind
from noetrium_platform.infrastructure.resources.lease.api import (
    LeaseState,
    ResourceIdentity,
    ResourceKind,
    ResourceLease,
    ResourceLeaseConflict,
    ResourceLeaseExpired,
    ResourceOwner,
    ResourceOwnership,
    ResourceOwnershipConflict,
)

from .sqlite_resource import expire_lease, expire_resource, next_fencing_token


def decode_resource_owner(row: tuple[object, ...]) -> ResourceOwner:
    return ResourceOwner(
        ResourceIdentity(ResourceKind(str(row[1])), str(row[2])),
        ScopeIdentity(ScopeKind(str(row[3])), str(row[4])),
        ResourceOwnership(str(row[5])),
    )


def decode_resource_lease(row: tuple[object, ...]) -> ResourceLease:
    return ResourceLease(
        str(row[0]),
        ResourceIdentity(ResourceKind(str(row[2])), str(row[3])),
        ScopeIdentity(ScopeKind(str(row[4])), str(row[5])),
        str(row[6]),
        LeaseState(str(row[7])),
        int(row[8]),
        int(row[9]),
        None if row[10] is None else float(row[10]),
        None if len(row) < 12 or row[11] is None else float(row[11]),
        None if len(row) < 13 or row[12] is None else float(row[12]),
    )


def ensure_resource_owner(conn: sqlite3.Connection, owner: ResourceOwner) -> None:
    row = conn.execute(
        "SELECT * FROM resource_owners WHERE resource_key=?",
        (owner.resource.key,),
    ).fetchone()
    if row is not None:
        if decode_resource_owner(row) != owner:
            raise ResourceOwnershipConflict(owner.resource.key)
        return
    conn.execute(
        "INSERT INTO resource_owners(resource_key,resource_kind,resource_id,"
        "scope_kind,scope_id,ownership) VALUES(?,?,?,?,?,?)",
        (
            owner.resource.key,
            owner.resource.kind.value,
            owner.resource.resource_id,
            owner.scope.kind.value,
            owner.scope.scope_id,
            owner.ownership.value,
        ),
    )


def acquire_resource_lease(
    conn: sqlite3.Connection,
    lease: ResourceLease,
    *,
    ttl_seconds: float | None,
    now_epoch_s: float,
) -> ResourceLease:
    if not math.isfinite(float(now_epoch_s)):
        raise ValueError("lease observation time must be finite")
    if ttl_seconds is not None and (
        not math.isfinite(float(ttl_seconds)) or ttl_seconds <= 0
    ):
        raise ValueError("lease ttl_seconds must be finite and > 0")
    owner = conn.execute(
        "SELECT 1 FROM resource_owners WHERE resource_key=?",
        (lease.resource.key,),
    ).fetchone()
    if owner is None:
        raise KeyError(lease.resource.key)
    expire_resource(conn, lease.resource.key, now_epoch_s)
    row = conn.execute(
        "SELECT * FROM resource_leases WHERE lease_id=?",
        (lease.lease_id,),
    ).fetchone()
    existing = None if row is None else decode_resource_lease(row)
    next_generation = lease.holder_generation
    if existing is not None:
        same_identity = (
            existing.lease_id == lease.lease_id
            and existing.resource == lease.resource
            and existing.holder_scope == lease.holder_scope
            and existing.purpose == lease.purpose
        )
        if not same_identity:
            raise ResourceLeaseConflict(lease.lease_id)
        if existing.state is LeaseState.ACTIVE:
            return existing
        next_generation = existing.holder_generation + 1
    active = conn.execute(
        "SELECT 1 FROM resource_leases WHERE resource_key=? AND state='active'",
        (lease.resource.key,),
    ).fetchone()
    if active is not None:
        raise ResourceLeaseConflict(
            f"resource already has an active lease: {lease.resource.key}"
        )
    fencing = next_fencing_token(conn, lease.resource.key)
    expires_at = (
        lease.expires_at_epoch_s
        if ttl_seconds is None
        else now_epoch_s + float(ttl_seconds)
    )
    granted = replace(
        lease,
        state=LeaseState.ACTIVE,
        holder_generation=next_generation,
        fencing_token=fencing,
        expires_at_epoch_s=expires_at,
        acquired_at_epoch_s=now_epoch_s,
        released_at_epoch_s=None,
    )
    values = (
        granted.resource.key,
        granted.resource.kind.value,
        granted.resource.resource_id,
        granted.holder_scope.kind.value,
        granted.holder_scope.scope_id,
        granted.purpose,
        granted.state.value,
        granted.holder_generation,
        granted.fencing_token,
        granted.expires_at_epoch_s,
        granted.acquired_at_epoch_s,
        granted.released_at_epoch_s,
    )
    try:
        if existing is None:
            conn.execute(
                "INSERT INTO resource_leases(lease_id,resource_key,resource_kind,"
                "resource_id,holder_scope_kind,holder_scope_id,purpose,state,"
                "holder_generation,fencing_token,expires_at_epoch_s,acquired_at_epoch_s,released_at_epoch_s) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (granted.lease_id, *values),
            )
        else:
            conn.execute(
                "UPDATE resource_leases SET resource_key=?,resource_kind=?,resource_id=?,"
                "holder_scope_kind=?,holder_scope_id=?,purpose=?,state=?,holder_generation=?,"
                "fencing_token=?,expires_at_epoch_s=?,acquired_at_epoch_s=?,released_at_epoch_s=? WHERE lease_id=?",
                (*values, granted.lease_id),
            )
    except sqlite3.IntegrityError as exc:
        raise ResourceLeaseConflict(granted.lease_id) from exc
    return granted


def renew_resource_lease(
    conn: sqlite3.Connection,
    lease_id: str,
    *,
    fencing_token: int,
    ttl_seconds: float,
    now_epoch_s: float,
) -> ResourceLease:
    if not math.isfinite(float(now_epoch_s)):
        raise ValueError("lease observation time must be finite")
    if not math.isfinite(float(ttl_seconds)) or ttl_seconds <= 0:
        raise ValueError("lease ttl_seconds must be finite and > 0")
    expire_lease(conn, lease_id, now_epoch_s)
    row = conn.execute(
        "SELECT * FROM resource_leases WHERE lease_id=?",
        (lease_id,),
    ).fetchone()
    if row is None:
        raise KeyError(lease_id)
    current = decode_resource_lease(row)
    if current.state is LeaseState.EXPIRED:
        raise ResourceLeaseExpired(lease_id)
    if current.state is not LeaseState.ACTIVE or current.fencing_token != fencing_token:
        raise ResourceLeaseConflict(f"stale lease fencing token: {lease_id}")
    expires_at = now_epoch_s + float(ttl_seconds)
    cursor = conn.execute(
        "UPDATE resource_leases SET expires_at_epoch_s=? "
        "WHERE lease_id=? AND state='active' AND fencing_token=?",
        (expires_at, lease_id, fencing_token),
    )
    if cursor.rowcount != 1:
        raise ResourceLeaseConflict(f"lease renewal lost authority: {lease_id}")
    return replace(current, expires_at_epoch_s=expires_at)


def release_resource_lease(
    conn: sqlite3.Connection,
    lease_id: str,
    *,
    now_epoch_s: float,
) -> ResourceLease:
    if not math.isfinite(float(now_epoch_s)):
        raise ValueError("lease observation time must be finite")
    expire_lease(conn, lease_id, now_epoch_s)
    row = conn.execute(
        "SELECT * FROM resource_leases WHERE lease_id=?",
        (lease_id,),
    ).fetchone()
    if row is None:
        raise KeyError(lease_id)
    current = decode_resource_lease(row)
    if current.state is not LeaseState.RELEASED:
        conn.execute(
            "UPDATE resource_leases SET state='released', released_at_epoch_s=? WHERE lease_id=?",
            (now_epoch_s, lease_id),
        )
        current = replace(
            current, state=LeaseState.RELEASED, released_at_epoch_s=now_epoch_s
        )
    return current


def reconcile_expired_resource_leases(
    conn: sqlite3.Connection,
    *,
    now_epoch_s: float,
    resource_kind: ResourceKind | None = None,
) -> tuple[ResourceLease, ...]:
    if not math.isfinite(float(now_epoch_s)):
        raise ValueError("lease observation time must be finite")
    where = (
        "state='active' AND expires_at_epoch_s IS NOT NULL AND expires_at_epoch_s<=?"
    )
    args: tuple[object, ...] = (now_epoch_s,)
    if resource_kind is not None:
        where += " AND resource_kind=?"
        args += (resource_kind.value,)
    rows = conn.execute(
        f"SELECT * FROM resource_leases WHERE {where} ORDER BY lease_id",
        args,
    ).fetchall()
    if rows:
        conn.executemany(
            "UPDATE resource_leases SET state='expired' WHERE lease_id=? AND state='active'",
            ((str(row[0]),) for row in rows),
        )
    return tuple(
        replace(decode_resource_lease(row), state=LeaseState.EXPIRED)
        for row in rows
    )


__all__ = [
    "acquire_resource_lease",
    "decode_resource_lease",
    "decode_resource_owner",
    "ensure_resource_owner",
    "reconcile_expired_resource_leases",
    "release_resource_lease",
    "renew_resource_lease",
]
