from __future__ import annotations

import math
import sqlite3

from dataclasses import replace
from pathlib import Path
from time import time

from noetrium_platform.infrastructure.resources.allocation.api import (
    AtomicEndpointReservationPort,
    EndpointAllocation,
    EndpointAllocationState,
    EndpointBindingProof,
    EndpointProtocol,
    EndpointReservationResult,
    EndpointReservationStatus,
    NetworkEndpoint,
)
from noetrium_platform.infrastructure.resources.lease.api import (
    LeaseState,
    ResourceKind,
    ResourceLease,
    ResourceLeaseConflict,
    ResourceOwner,
    ResourceOwnershipConflict,
)
from noetrium_platform.infrastructure.resources.providers.sqlite_connection import durable_sqlite_connection
from noetrium_platform.infrastructure.resources.providers.sqlite_lease_ops import (
    acquire_resource_lease,
    decode_resource_lease,
    ensure_resource_owner,
    reconcile_expired_resource_leases,
    release_resource_lease,
    renew_resource_lease,
)
from noetrium_platform.infrastructure.resources.providers.sqlite_resource import (
    ensure_resource_schema,
    expire_lease,
)
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind


class SQLiteEndpointAllocationStore(AtomicEndpointReservationPort):
    """Atomic SQLite authority for endpoint allocation + resource lease state.

    The provider owns persistence mechanics only. Candidate ordering, probing,
    retry policy and user-facing allocation errors remain in runtime.
    """

    SCHEMA_VERSION = 4

    _SELECT = (
        "allocation_id,host,port,protocol,lease_id,holder_scope_kind,holder_scope_id,"
        "purpose,request_digest,state,lease_holder_generation,lease_fencing_token,"
        "lease_expires_at_epoch_s,binding_proof_digest,binding_binder_identity_digest,"
        "binding_evidence_ref,bound_at_epoch_s"
    )

    def __init__(self, path: str | Path, *, timeout_seconds: float = 30.0) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not math.isfinite(float(timeout_seconds)) or timeout_seconds <= 0:
            raise ValueError("SQLite endpoint timeout_seconds must be finite and positive")
        self.timeout_seconds = float(timeout_seconds)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                ensure_resource_schema(conn)
                self._ensure_schema(conn)
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def _connection(self):
        return durable_sqlite_connection(self.path, timeout_seconds=self.timeout_seconds)

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE IF NOT EXISTS endpoint_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS endpoint_allocations(
                allocation_id TEXT PRIMARY KEY,
                host TEXT NOT NULL,
                port INTEGER NOT NULL,
                protocol TEXT NOT NULL,
                lease_id TEXT NOT NULL,
                holder_scope_kind TEXT NOT NULL,
                holder_scope_id TEXT NOT NULL,
                purpose TEXT NOT NULL,
                request_digest TEXT NOT NULL,
                state TEXT NOT NULL,
                lease_holder_generation INTEGER NOT NULL DEFAULT 1,
                lease_fencing_token INTEGER NOT NULL DEFAULT 1,
                lease_expires_at_epoch_s REAL,
                binding_proof_digest TEXT,
                binding_binder_identity_digest TEXT,
                binding_evidence_ref TEXT,
                bound_at_epoch_s REAL
            )
            """
        )
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(endpoint_allocations)").fetchall()}
        if "lease_holder_generation" not in columns:
            conn.execute(
                "ALTER TABLE endpoint_allocations ADD COLUMN lease_holder_generation INTEGER NOT NULL DEFAULT 1"
            )
        if "lease_fencing_token" not in columns:
            conn.execute(
                "ALTER TABLE endpoint_allocations ADD COLUMN lease_fencing_token INTEGER NOT NULL DEFAULT 1"
            )
        if "lease_expires_at_epoch_s" not in columns:
            conn.execute("ALTER TABLE endpoint_allocations ADD COLUMN lease_expires_at_epoch_s REAL")
        if "binding_proof_digest" not in columns:
            conn.execute("ALTER TABLE endpoint_allocations ADD COLUMN binding_proof_digest TEXT")
        if "binding_binder_identity_digest" not in columns:
            conn.execute("ALTER TABLE endpoint_allocations ADD COLUMN binding_binder_identity_digest TEXT")
        if "binding_evidence_ref" not in columns:
            conn.execute("ALTER TABLE endpoint_allocations ADD COLUMN binding_evidence_ref TEXT")
        if "bound_at_epoch_s" not in columns:
            conn.execute("ALTER TABLE endpoint_allocations ADD COLUMN bound_at_epoch_s REAL")
        # v2 called a DB reservation ACTIVE even though no OS bind proof existed.
        # Migrate fail-closed: such rows are reservations until a runtime authority
        # supplies a fencing-bound listener attestation.
        conn.execute("UPDATE endpoint_allocations SET state='reserved' WHERE state='active'")
        conn.execute(
            "UPDATE endpoint_allocations SET state='reserved', binding_proof_digest=NULL, "
            "binding_binder_identity_digest=NULL, binding_evidence_ref=NULL, bound_at_epoch_s=NULL "
            "WHERE state='bound' AND binding_binder_identity_digest IS NULL"
        )
        conn.execute("DROP INDEX IF EXISTS active_endpoint_allocations")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS live_endpoint_allocations "
            "ON endpoint_allocations(state, allocation_id)"
        )
        conn.execute(
            "INSERT INTO endpoint_meta(key,value) VALUES('schema_version',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(self.SCHEMA_VERSION),),
        )

    @staticmethod
    def _decode(row: tuple[object, ...]) -> EndpointAllocation:
        return EndpointAllocation(
            allocation_id=str(row[0]),
            endpoint=NetworkEndpoint(str(row[1]), int(row[2]), EndpointProtocol(str(row[3]))),
            lease_id=str(row[4]),
            holder_scope=ScopeIdentity(ScopeKind(str(row[5])), str(row[6])),
            purpose=str(row[7]),
            request_digest=str(row[8]),
            state=EndpointAllocationState(str(row[9])),
            lease_holder_generation=int(row[10]),
            lease_fencing_token=int(row[11]),
            lease_expires_at_epoch_s=None if row[12] is None else float(row[12]),
            binding_proof_digest=None if row[13] is None else str(row[13]),
            binding_binder_identity_digest=None if row[14] is None else str(row[14]),
            binding_evidence_ref=None if row[15] is None else str(row[15]),
            bound_at_epoch_s=None if row[16] is None else float(row[16]),
        )

    @staticmethod
    def _owner_matches(row: tuple[object, ...], owner: ResourceOwner) -> bool:
        return (
            str(row[0]) == owner.resource.kind.value
            and str(row[1]) == owner.resource.resource_id
            and str(row[2]) == owner.scope.kind.value
            and str(row[3]) == owner.scope.scope_id
            and str(row[4]) == owner.ownership.value
        )

    def _reconcile_one(
        self, conn: sqlite3.Connection, allocation_id: str, now_epoch_s: float
    ) -> EndpointAllocation | None:
        row = conn.execute(
            f"SELECT {self._SELECT} FROM endpoint_allocations WHERE allocation_id=?",
            (allocation_id,),
        ).fetchone()
        if row is None:
            return None
        allocation = self._decode(row)
        if not allocation.state.is_live:
            return allocation
        expire_lease(conn, allocation.lease_id, now_epoch_s)
        lease_row = conn.execute(
            "SELECT * FROM resource_leases WHERE lease_id=?",
            (allocation.lease_id,),
        ).fetchone()
        lease = None if lease_row is None else decode_resource_lease(lease_row)
        if (
            lease is None
            or lease.state is not LeaseState.ACTIVE
            or lease.fencing_token != allocation.lease_fencing_token
        ):
            conn.execute(
                "UPDATE endpoint_allocations SET state='released' WHERE allocation_id=? AND state IN ('reserved','bound')",
                (allocation_id,),
            )
            return replace(allocation, state=EndpointAllocationState.RELEASED)
        return allocation

    def reserve(
        self,
        *,
        owner: ResourceOwner,
        lease: ResourceLease,
        allocation: EndpointAllocation,
        ttl_seconds: float,
        now: float | None = None,
    ) -> EndpointReservationResult:
        if not math.isfinite(float(ttl_seconds)) or ttl_seconds <= 0:
            raise ValueError("endpoint lease ttl_seconds must be finite and > 0")
        if lease.resource != allocation.endpoint.resource or lease.lease_id != allocation.lease_id:
            raise ValueError("endpoint reservation lease/allocation identity mismatch")
        if lease.resource.kind is not ResourceKind.NETWORK_ENDPOINT:
            raise ValueError("endpoint reservation requires a network-endpoint resource")
        now_epoch_s = time() if now is None else float(now)
        if not math.isfinite(now_epoch_s):
            raise ValueError("endpoint observation time must be finite")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                existing = self._reconcile_one(conn, allocation.allocation_id, now_epoch_s)
                if existing is not None:
                    conn.commit()
                    return EndpointReservationResult(EndpointReservationStatus.EXISTING, existing)

                try:
                    ensure_resource_owner(conn, owner)
                except ResourceOwnershipConflict:
                    conn.commit()
                    return EndpointReservationResult(
                        EndpointReservationStatus.OWNER_CONFLICT,
                        detail=f"resource owner conflict: {owner.resource.key}",
                    )

                try:
                    granted_lease = acquire_resource_lease(
                        conn,
                        lease,
                        ttl_seconds=ttl_seconds,
                        now_epoch_s=now_epoch_s,
                    )
                except ResourceLeaseConflict as exc:
                    if not str(exc).startswith("resource already has an active lease:"):
                        raise
                    conn.commit()
                    return EndpointReservationResult(
                        EndpointReservationStatus.RESOURCE_BUSY,
                        detail=f"resource already leased: {lease.resource.key}",
                    )

                granted_allocation = replace(
                    allocation,
                    state=EndpointAllocationState.RESERVED,
                    lease_holder_generation=granted_lease.holder_generation,
                    lease_fencing_token=granted_lease.fencing_token,
                    lease_expires_at_epoch_s=granted_lease.expires_at_epoch_s,
                )
                conn.execute(
                    """
                    INSERT INTO endpoint_allocations(
                        allocation_id,host,port,protocol,lease_id,holder_scope_kind,
                        holder_scope_id,purpose,request_digest,state,
                        lease_holder_generation,lease_fencing_token,lease_expires_at_epoch_s
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        granted_allocation.allocation_id, granted_allocation.endpoint.host,
                        granted_allocation.endpoint.port, granted_allocation.endpoint.protocol.value,
                        granted_allocation.lease_id, granted_allocation.holder_scope.kind.value,
                        granted_allocation.holder_scope.scope_id, granted_allocation.purpose,
                        granted_allocation.request_digest, granted_allocation.state.value,
                        granted_allocation.lease_holder_generation,
                        granted_allocation.lease_fencing_token,
                        granted_allocation.lease_expires_at_epoch_s,
                    ),
                )
                conn.commit()
                return EndpointReservationResult(
                    EndpointReservationStatus.RESERVED,
                    granted_allocation,
                    granted_lease,
                )
            except BaseException:
                conn.rollback()
                raise

    def confirm_bound(
        self, proof: EndpointBindingProof, *, now: float | None = None
    ) -> EndpointAllocation:
        now_epoch_s = time() if now is None else float(now)
        if not math.isfinite(now_epoch_s):
            raise ValueError("endpoint observation time must be finite")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                current = self._reconcile_one(conn, proof.allocation_id, now_epoch_s)
                if current is None:
                    raise KeyError(proof.allocation_id)
                if current.state is EndpointAllocationState.RELEASED:
                    raise RuntimeError(f"endpoint allocation is released: {proof.allocation_id}")
                if current.endpoint != proof.endpoint:
                    raise RuntimeError(
                        f"endpoint binding proof endpoint mismatch: {proof.allocation_id}"
                    )
                if current.lease_fencing_token != proof.lease_fencing_token:
                    raise RuntimeError(
                        f"endpoint binding proof fencing lost: {proof.allocation_id}"
                    )
                proof_digest = proof.digest()
                if current.state is EndpointAllocationState.BOUND:
                    if (
                        current.binding_proof_digest == proof_digest
                        and current.binding_evidence_ref == proof.evidence_ref
                        and current.bound_at_epoch_s == proof.observed_at_epoch_s
                    ):
                        conn.commit()
                        return current
                    raise RuntimeError(
                        f"endpoint allocation already has a different binding proof: {proof.allocation_id}"
                    )
                cursor = conn.execute(
                    """
                    UPDATE endpoint_allocations
                    SET state='bound', binding_proof_digest=?, binding_binder_identity_digest=?,
                        binding_evidence_ref=?, bound_at_epoch_s=?
                    WHERE allocation_id=? AND state='reserved' AND lease_fencing_token=?
                    """,
                    (
                        proof_digest,
                        proof.binder_identity_digest,
                        proof.evidence_ref,
                        proof.observed_at_epoch_s,
                        proof.allocation_id,
                        proof.lease_fencing_token,
                    ),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError(
                        f"endpoint binding transition lost authority: {proof.allocation_id}"
                    )
                conn.commit()
                return replace(
                    current,
                    state=EndpointAllocationState.BOUND,
                    binding_proof_digest=proof_digest,
                    binding_binder_identity_digest=proof.binder_identity_digest,
                    binding_evidence_ref=proof.evidence_ref,
                    bound_at_epoch_s=proof.observed_at_epoch_s,
                )
            except BaseException:
                conn.rollback()
                raise

    def replace_bound(
        self, proof: EndpointBindingProof, *, expected_previous_binding_proof_digest: str,
        now: float | None = None,
    ) -> EndpointAllocation:
        if len(expected_previous_binding_proof_digest) != 64 or any(
            character not in "0123456789abcdef" for character in expected_previous_binding_proof_digest
        ):
            raise ValueError("expected previous endpoint binding proof digest must be canonical SHA-256")
        now_epoch_s = time() if now is None else float(now)
        if not math.isfinite(now_epoch_s):
            raise ValueError("endpoint observation time must be finite")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                current = self._reconcile_one(conn, proof.allocation_id, now_epoch_s)
                if current is None:
                    raise KeyError(proof.allocation_id)
                if current.state is not EndpointAllocationState.BOUND:
                    raise RuntimeError(f"endpoint allocation is not bound: {proof.allocation_id}")
                if current.endpoint != proof.endpoint:
                    raise RuntimeError(f"endpoint binding proof endpoint mismatch: {proof.allocation_id}")
                if current.lease_fencing_token != proof.lease_fencing_token:
                    raise RuntimeError(f"endpoint binding proof fencing lost: {proof.allocation_id}")
                if current.binding_proof_digest != expected_previous_binding_proof_digest:
                    raise RuntimeError(f"endpoint binding replacement lost prior generation: {proof.allocation_id}")
                if current.binding_binder_identity_digest == proof.binder_identity_digest:
                    raise RuntimeError(f"endpoint binding replacement must use a new binder generation: {proof.allocation_id}")
                proof_digest = proof.digest()
                cursor = conn.execute(
                    "UPDATE endpoint_allocations SET binding_proof_digest=?, binding_binder_identity_digest=?, "
                    "binding_evidence_ref=?, bound_at_epoch_s=? WHERE allocation_id=? AND state='bound' "
                    "AND lease_fencing_token=? AND binding_proof_digest=?",
                    (proof_digest, proof.binder_identity_digest, proof.evidence_ref, proof.observed_at_epoch_s,
                     proof.allocation_id, proof.lease_fencing_token, expected_previous_binding_proof_digest),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError(f"endpoint binding replacement lost authority: {proof.allocation_id}")
                conn.commit()
                return replace(current, binding_proof_digest=proof_digest,
                    binding_binder_identity_digest=proof.binder_identity_digest,
                    binding_evidence_ref=proof.evidence_ref, bound_at_epoch_s=proof.observed_at_epoch_s)
            except BaseException:
                conn.rollback()
                raise

    def renew(
        self,
        allocation_id: str,
        *,
        ttl_seconds: float,
        now: float | None = None,
    ) -> EndpointAllocation:
        if not math.isfinite(float(ttl_seconds)) or ttl_seconds <= 0:
            raise ValueError("endpoint lease ttl_seconds must be finite and > 0")
        now_epoch_s = time() if now is None else float(now)
        if not math.isfinite(now_epoch_s):
            raise ValueError("endpoint observation time must be finite")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self._reconcile_one(conn, allocation_id, now_epoch_s)
            if current is None:
                conn.rollback()
                raise KeyError(allocation_id)
            if not current.state.is_live:
                conn.rollback()
                raise RuntimeError(f"endpoint allocation is not active: {allocation_id}")
            try:
                renewed_lease = renew_resource_lease(
                    conn,
                    current.lease_id,
                    fencing_token=current.lease_fencing_token,
                    ttl_seconds=ttl_seconds,
                    now_epoch_s=now_epoch_s,
                )
                expires_at = renewed_lease.expires_at_epoch_s
                conn.execute(
                    "UPDATE endpoint_allocations SET lease_expires_at_epoch_s=? WHERE allocation_id=?",
                    (expires_at, allocation_id),
                )
                conn.commit()
                return replace(current, lease_expires_at_epoch_s=expires_at)
            except BaseException:
                conn.rollback()
                raise

    def renew_many(
        self,
        allocation_ids: tuple[str, ...],
        *,
        ttl_seconds: float,
        now: float | None = None,
    ) -> tuple[EndpointAllocation, ...]:
        if not allocation_ids:
            return ()
        if len(set(allocation_ids)) != len(allocation_ids):
            raise ValueError("endpoint allocation ids must be unique")
        if not math.isfinite(float(ttl_seconds)) or ttl_seconds <= 0:
            raise ValueError("endpoint lease ttl_seconds must be finite and > 0")
        now_epoch_s = time() if now is None else float(now)
        expires_at = now_epoch_s + ttl_seconds
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                current_rows: list[EndpointAllocation] = []
                for allocation_id in allocation_ids:
                    current = self._reconcile_one(conn, allocation_id, now_epoch_s)
                    if current is None:
                        raise KeyError(allocation_id)
                    if not current.state.is_live:
                        raise RuntimeError(f"endpoint allocation is not active: {allocation_id}")
                    current_rows.append(current)
                renewed_leases = [
                    renew_resource_lease(
                        conn,
                        row.lease_id,
                        fencing_token=row.lease_fencing_token,
                        ttl_seconds=ttl_seconds,
                        now_epoch_s=now_epoch_s,
                    )
                    for row in current_rows
                ]
                if any(row.expires_at_epoch_s != expires_at for row in renewed_leases):
                    raise RuntimeError("endpoint lease renewal produced inconsistent expiry")
                conn.executemany(
                    "UPDATE endpoint_allocations SET lease_expires_at_epoch_s=? WHERE allocation_id=?",
                    [(expires_at, row.allocation_id) for row in current_rows],
                )
                conn.commit()
                return tuple(replace(row, lease_expires_at_epoch_s=expires_at) for row in current_rows)
            except BaseException:
                conn.rollback()
                raise

    def release(self, allocation_id: str) -> EndpointAllocation:
        now_epoch_s = time()
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self._reconcile_one(conn, allocation_id, now_epoch_s)
            if current is None:
                conn.rollback()
                raise KeyError(allocation_id)
            if current.state is EndpointAllocationState.RELEASED:
                conn.commit()
                return current
            release_resource_lease(
                conn, current.lease_id, now_epoch_s=now_epoch_s
            )
            conn.execute(
                "UPDATE endpoint_allocations SET state='released' WHERE allocation_id=?",
                (allocation_id,),
            )
            conn.commit()
            return replace(current, state=EndpointAllocationState.RELEASED)

    def get(self, allocation_id: str) -> EndpointAllocation | None:
        # Point reads are strongly reconciled against the authoritative lease.
        # This is still O(1): both allocation_id and lease_id are indexed keys.
        now_epoch_s = time()
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                current = self._reconcile_one(conn, allocation_id, now_epoch_s)
                conn.commit()
                return current
            except BaseException:
                conn.rollback()
                raise

    def active(self) -> tuple[EndpointAllocation, ...]:
        self.reconcile_orphans()
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT {self._SELECT} FROM endpoint_allocations "
                "WHERE state IN ('reserved','bound') ORDER BY allocation_id"
            ).fetchall()
        return tuple(self._decode(row) for row in rows)

    def reconcile_orphans(self, *, now: float | None = None) -> tuple[EndpointAllocation, ...]:
        now_epoch_s = time() if now is None else float(now)
        if not math.isfinite(now_epoch_s):
            raise ValueError("endpoint observation time must be finite")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            reconcile_expired_resource_leases(
                conn,
                now_epoch_s=now_epoch_s,
                resource_kind=ResourceKind.NETWORK_ENDPOINT,
            )
            orphan_rows = conn.execute(
                f"""
                SELECT {', '.join('a.' + part for part in self._SELECT.split(','))}
                FROM endpoint_allocations AS a
                LEFT JOIN resource_leases AS l ON l.lease_id=a.lease_id
                WHERE a.state IN ('reserved','bound') AND (
                    l.lease_id IS NULL OR l.state!='active' OR l.fencing_token!=a.lease_fencing_token
                )
                ORDER BY a.allocation_id
                """
            ).fetchall()
            if orphan_rows:
                conn.executemany(
                    "UPDATE endpoint_allocations SET state='released' WHERE allocation_id=? AND state IN ('reserved','bound')",
                    ((str(row[0]),) for row in orphan_rows),
                )
            conn.commit()
        return tuple(replace(self._decode(row), state=EndpointAllocationState.RELEASED) for row in orphan_rows)


__all__ = ["SQLiteEndpointAllocationStore"]
