from __future__ import annotations

import json
import math
import sqlite3

from noetrium_platform.infrastructure.resources.lease.api import (
    LeaseClockReading,
    ResourceLeaseClockConflict,
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


__all__ = [
    "RESOURCE_SCHEMA_VERSION",
    "authoritative_lease_now",
    "ensure_resource_schema",
    "expire_lease",
    "expire_resource",
    "next_fencing_token",
]
