from __future__ import annotations

from dataclasses import replace
import json
import math
import sqlite3

from noetrium_platform.foundation.governance.api import ScopeIdentity, ScopeKind
from noetrium_platform.infrastructure.resources.lease.api import (
    LeaseClockReading,
    LeaseState,
    ResourceIdentity,
    ResourceKind,
    ResourceLease,
    ResourceLeaseClockConflict,
    ResourceLeaseConflict,
    ResourceLeaseExpired,
    ResourceOwner,
    ResourceOwnership,
    ResourceOwnershipConflict,
)


RESOURCE_SCHEMA_VERSION = 5


def ensure_resource_schema(conn: sqlite3.Connection) -> None:
    """Create/migrate resource ownership and lease tables in one writer transaction.

    The caller owns transaction scope. Column-presence checks make v1 -> v2
    migration idempotent even when multiple provider constructors race.
    """

    conn.execute("CREATE TABLE IF NOT EXISTS resource_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS resource_owners(
            resource_key TEXT PRIMARY KEY,
            resource_kind TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            scope_kind TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            ownership TEXT NOT NULL,
            UNIQUE(resource_kind, resource_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS resource_leases(
            lease_id TEXT PRIMARY KEY,
            resource_key TEXT NOT NULL REFERENCES resource_owners(resource_key),
            resource_kind TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            holder_scope_kind TEXT NOT NULL,
            holder_scope_id TEXT NOT NULL,
            purpose TEXT NOT NULL,
            state TEXT NOT NULL,
            holder_generation INTEGER NOT NULL DEFAULT 1,
            fencing_token INTEGER NOT NULL DEFAULT 1,
            expires_at_epoch_s REAL,
            acquired_at_epoch_s REAL,
            released_at_epoch_s REAL
        )
        """
    )
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(resource_leases)").fetchall()}
    if "holder_generation" not in columns:
        conn.execute("ALTER TABLE resource_leases ADD COLUMN holder_generation INTEGER NOT NULL DEFAULT 1")
    if "fencing_token" not in columns:
        conn.execute("ALTER TABLE resource_leases ADD COLUMN fencing_token INTEGER NOT NULL DEFAULT 1")
    if "expires_at_epoch_s" not in columns:
        conn.execute("ALTER TABLE resource_leases ADD COLUMN expires_at_epoch_s REAL")
    if "acquired_at_epoch_s" not in columns:
        conn.execute("ALTER TABLE resource_leases ADD COLUMN acquired_at_epoch_s REAL")
    if "released_at_epoch_s" not in columns:
        conn.execute("ALTER TABLE resource_leases ADD COLUMN released_at_epoch_s REAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS resource_lease_fencing(
            resource_key TEXT PRIMARY KEY REFERENCES resource_owners(resource_key),
            last_token INTEGER NOT NULL
        )
        """
    )
    # Seed counters for v1 rows before assigning any future lease.
    conn.execute(
        """
        INSERT INTO resource_lease_fencing(resource_key,last_token)
        SELECT resource_key, MAX(fencing_token)
        FROM resource_leases
        GROUP BY resource_key
        ON CONFLICT(resource_key) DO UPDATE SET
            last_token = MAX(resource_lease_fencing.last_token, excluded.last_token)
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS one_active_resource_lease "
        "ON resource_leases(resource_key) WHERE state='active'"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS expiring_resource_leases "
        "ON resource_leases(expires_at_epoch_s) "
        "WHERE state='active' AND expires_at_epoch_s IS NOT NULL"
    )
    conn.execute(
        "INSERT INTO resource_meta(key,value) VALUES('schema_version',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(RESOURCE_SCHEMA_VERSION),),
    )



_LEASE_CLOCK_ANCHOR_KEY = "lease_clock_anchor_v1"


def _boot_anchor_epoch(reading: LeaseClockReading) -> float:
    logical_epoch = float(reading.wall_epoch_seconds)
    if not math.isfinite(logical_epoch) or logical_epoch <= 0:
        raise ResourceLeaseClockConflict(
            "lease wall clock must be positive when establishing a durable boot anchor"
        )
    return logical_epoch


def authoritative_lease_now(
    conn: sqlite3.Connection,
    reading: LeaseClockReading,
) -> float:
    """Resolve durable lease time without trusting mutable wall clock.

    The resource DB is bound to one stable host clock domain. Same-host reboot
    revokes every active lease from the old boot before the new boot can mutate
    ownership. A different host never steals lease authority implicitly.
    """

    if not isinstance(reading, LeaseClockReading):
        raise TypeError("lease clock reading must be LeaseClockReading")
    row = conn.execute(
        "SELECT value FROM resource_meta WHERE key=?",
        (_LEASE_CLOCK_ANCHOR_KEY,),
    ).fetchone()
    if row is None:
        logical_epoch = _boot_anchor_epoch(reading)
        payload = {
            "host_identity_digest": reading.host_identity_digest,
            "boot_identity_digest": reading.boot_identity_digest,
            "elapsed_seconds": reading.elapsed_seconds,
            "logical_epoch_seconds": logical_epoch,
        }
        conn.execute(
            "INSERT INTO resource_meta(key,value) VALUES(?,?)",
            (
                _LEASE_CLOCK_ANCHOR_KEY,
                json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )
        return logical_epoch

    try:
        payload = json.loads(str(row[0]))
        host = str(payload["host_identity_digest"])
        boot = str(payload["boot_identity_digest"])
        anchor_elapsed = float(payload["elapsed_seconds"])
        anchor_epoch = float(payload["logical_epoch_seconds"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ResourceLeaseClockConflict(
            "durable lease clock anchor is malformed"
        ) from exc

    if (
        len(host) != 64
        or len(boot) != 64
        or any(ch not in "0123456789abcdef" for ch in host)
        or any(ch not in "0123456789abcdef" for ch in boot)
        or not math.isfinite(anchor_elapsed)
        or anchor_elapsed < 0
        or not math.isfinite(anchor_epoch)
        or anchor_epoch <= 0
    ):
        raise ResourceLeaseClockConflict(
            "durable lease clock anchor is invalid"
        )
    if host != reading.host_identity_digest:
        raise ResourceLeaseClockConflict(
            "resource authority belongs to a different host clock domain"
        )

    if boot != reading.boot_identity_digest:
        # A reboot proves the old process generation cannot renew. Expiration
        # only revokes lease mutation authority; physical resource providers
        # still quarantine endpoint/GPU/container truth until reconciliation.
        conn.execute(
            "UPDATE resource_leases SET state='expired' WHERE state='active'"
        )
        logical_epoch = _boot_anchor_epoch(reading)
        replacement = {
            "host_identity_digest": reading.host_identity_digest,
            "boot_identity_digest": reading.boot_identity_digest,
            "elapsed_seconds": reading.elapsed_seconds,
            "logical_epoch_seconds": logical_epoch,
        }
        conn.execute(
            "UPDATE resource_meta SET value=? WHERE key=?",
            (
                json.dumps(
                    replacement,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                _LEASE_CLOCK_ANCHOR_KEY,
            ),
        )
        return logical_epoch

    if reading.elapsed_seconds < anchor_elapsed:
        raise ResourceLeaseClockConflict(
            "same-boot suspend-aware lease clock moved backwards"
        )
    return anchor_epoch + (reading.elapsed_seconds - anchor_elapsed)

def expire_resource(conn: sqlite3.Connection, resource_key: str, now_epoch_s: float) -> int:
    return conn.execute(
        """
        UPDATE resource_leases
        SET state='expired'
        WHERE resource_key=? AND state='active'
          AND expires_at_epoch_s IS NOT NULL AND expires_at_epoch_s<=?
        """,
        (resource_key, now_epoch_s),
    ).rowcount


def expire_lease(conn: sqlite3.Connection, lease_id: str, now_epoch_s: float) -> int:
    return conn.execute(
        """
        UPDATE resource_leases
        SET state='expired'
        WHERE lease_id=? AND state='active'
          AND expires_at_epoch_s IS NOT NULL AND expires_at_epoch_s<=?
        """,
        (lease_id, now_epoch_s),
    ).rowcount


def next_fencing_token(conn: sqlite3.Connection, resource_key: str) -> int:
    row = conn.execute(
        """
        INSERT INTO resource_lease_fencing(resource_key,last_token) VALUES(?,1)
        ON CONFLICT(resource_key) DO UPDATE SET last_token=last_token+1
        RETURNING last_token
        """,
        (resource_key,),
    ).fetchone()
    if row is None:
        raise RuntimeError("failed to allocate resource fencing token")
    return int(row[0])


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
    fencing_token: int,
    now_epoch_s: float,
) -> ResourceLease:
    if not math.isfinite(float(now_epoch_s)):
        raise ValueError("lease observation time must be finite")
    if type(fencing_token) is not int or fencing_token < 1:
        raise ValueError("lease release fencing_token must be a positive integer")
    expire_lease(conn, lease_id, now_epoch_s)
    row = conn.execute(
        "SELECT * FROM resource_leases WHERE lease_id=?",
        (lease_id,),
    ).fetchone()
    if row is None:
        raise KeyError(lease_id)
    current = decode_resource_lease(row)
    if current.fencing_token != fencing_token:
        raise ResourceLeaseConflict(f"stale lease fencing token: {lease_id}")
    if current.state is LeaseState.EXPIRED:
        raise ResourceLeaseExpired(lease_id)
    if current.state is LeaseState.RELEASED:
        return current
    cursor = conn.execute(
        "UPDATE resource_leases SET state='released', released_at_epoch_s=? "
        "WHERE lease_id=? AND state='active' AND fencing_token=?",
        (now_epoch_s, lease_id, fencing_token),
    )
    if cursor.rowcount != 1:
        raise ResourceLeaseConflict(f"lease release lost authority: {lease_id}")
    return replace(
        current, state=LeaseState.RELEASED, released_at_epoch_s=now_epoch_s
    )


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
    "RESOURCE_SCHEMA_VERSION",
    "acquire_resource_lease",
    "authoritative_lease_now",
    "decode_resource_lease",
    "decode_resource_owner",
    "ensure_resource_owner",
    "ensure_resource_schema",
    "expire_lease",
    "expire_resource",
    "next_fencing_token",
    "reconcile_expired_resource_leases",
    "release_resource_lease",
    "renew_resource_lease",
]
