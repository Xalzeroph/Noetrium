from __future__ import annotations

import json
import math
import sqlite3
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Callable, Mapping
from threading import Event, Lock

from noetrium_platform.foundation.kernel.kernel import (
    JsonValue,
    canonical_digest,
    strict_finite_json_text,
    strict_json_loads,
    thaw_json,
    ComplexityBound,
    ComplexityContract,
    add_cost_work,
    set_cost_scale,
    LeaseClockPort,
    LeaseClockReading,
    LocalLeaseClock,
)
from noetrium_platform.foundation.kernel.unit import NoetriumUnit, UnitRef
from noetrium_platform.foundation.kernel.event import causal_event, causal_topological_order, event_field, event_ref_digest
from noetrium_platform.foundation.kernel.truth import TruthModality, truth_modality
from noetrium_platform.foundation.kernel.unit_codec import decode_unit, encode_unit
from noetrium_platform.foundation.governance.api import (
    PLATFORM_SCOPE,
    is_scope_unit,
    scope_from_data,
    scope_key,
    scope_kind,
    scope_requires_live_lease,
    scope_to_data,
    validate_scope_parent,
)
from noetrium_platform.foundation.kernel.kernel.durability.sqlite import (
    DurableSQLiteWriterOwner,
    durable_sqlite_reader,
    immediate_sqlite_transaction,
    sqlite_read_snapshot,
)

from ..api import (
    AuthorityGeneration,
    AuthoritySnapshot,
    ClaimAggregate,
    PhysicalResourceProvider,
    ResourceCapacity,
    ResourceClaimConflict,
    ResourceObservationNotReady,
    ResourceRealizationSpec,
    ReconcileActionKind,
    TicketState,
    is_resource_capacity_fact,
    is_realization_spec_fact,
    capacity_field,
    realization_spec_fact,
    realization_spec_field,
    resource_capacity_fact,
    authority_lease,
    binding_field,
    claim_field,
    compose_claims,
    is_authority_lease,
    is_physical_identity,
    is_realization_binding,
    is_realization_ticket,
    is_resource_claim,
    is_resource_observation,
    lease_field,
    lease_live_at,
    observation_field,
    physical_field,
    physical_identity,
    realization_binding,
    realization_ticket,
    resource_claim,
    resource_observation,
    ticket_field,
)


_CLAIM_AGGREGATE_META_KEY = "claim-aggregate-v1"
_CLAIM_AGGREGATE_VERSION = "1"
_AUTHORITY_SCHEMA_META_KEY = "resource-authority-schema"
_AUTHORITY_SCHEMA_VERSION = "resource-authority-v9"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS resource_authority_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resource_authority_events (
    event_digest TEXT PRIMARY KEY,
    authority_domain TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 0),
    modality TEXT NOT NULL CHECK (
        modality IN ('declared', 'authorized', 'observed', 'evidenced')
    ),
    resource_key TEXT NOT NULL,
    payload BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_resource_authority_events_domain
    ON resource_authority_events(authority_domain, event_digest);
CREATE INDEX IF NOT EXISTS idx_resource_authority_events_resource
    ON resource_authority_events(resource_key, event_digest);
CREATE TABLE IF NOT EXISTS resource_authority_event_heads (
    authority_domain TEXT PRIMARY KEY,
    event_digest TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 0)
);
CREATE TABLE IF NOT EXISTS resource_authority_generations (
    resource_key TEXT PRIMARY KEY,
    generation INTEGER NOT NULL CHECK (generation >= 1)
);
CREATE TABLE IF NOT EXISTS resource_authority_capacity (
    dimension TEXT PRIMARY KEY,
    capacity INTEGER NOT NULL CHECK (capacity >= 0)
);
CREATE TABLE IF NOT EXISTS resource_authority_claims (
    claim_id TEXT PRIMARY KEY,
    resource_key TEXT NOT NULL,
    holder_key TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 1),
    amounts_json TEXT NOT NULL,
    shared_json TEXT NOT NULL,
    exclusive_json TEXT NOT NULL,
    attributes_json TEXT NOT NULL,
    owner_scope_key TEXT,
    scope_generation INTEGER,
    scope_lease_id TEXT,
    owner_lease_id TEXT,
    released INTEGER NOT NULL DEFAULT 0 CHECK (released IN (0, 1))
);
CREATE INDEX IF NOT EXISTS idx_resource_authority_claims_active
    ON resource_authority_claims(released, resource_key);
CREATE INDEX IF NOT EXISTS idx_resource_authority_claims_live_order
    ON resource_authority_claims(claim_id) WHERE released=0;
CREATE INDEX IF NOT EXISTS idx_resource_authority_claims_live_holder
    ON resource_authority_claims(holder_key, claim_id) WHERE released=0;
CREATE INDEX IF NOT EXISTS idx_resource_authority_claims_live_kind_resource
    ON resource_authority_claims(
        json_extract(attributes_json, '$.attributes.kind'), resource_key
    ) WHERE released=0;
CREATE INDEX IF NOT EXISTS idx_resource_authority_claims_live_parent
    ON resource_authority_claims(
        json_extract(attributes_json, '$.attributes.parent_claim_id')
    ) WHERE released=0
      AND json_extract(attributes_json, '$.attributes.parent_claim_id') IS NOT NULL;
CREATE TABLE IF NOT EXISTS resource_authority_claim_amount_usage (
    dimension TEXT PRIMARY KEY,
    amount INTEGER NOT NULL CHECK (amount >= 0)
);
CREATE TABLE IF NOT EXISTS resource_authority_claim_shared_usage (
    token TEXT PRIMARY KEY,
    refcount INTEGER NOT NULL CHECK (refcount >= 1)
);
CREATE TABLE IF NOT EXISTS resource_authority_claim_exclusive_usage (
    token TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resource_authority_leases (
    lease_id TEXT PRIMARY KEY,
    resource_key TEXT NOT NULL,
    holder_key TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 1),
    expires_at_epoch_s REAL,
    acquired_at_epoch_s REAL,
    owner_scope_key TEXT,
    scope_generation INTEGER,
    scope_lease_id TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    released INTEGER NOT NULL DEFAULT 0 CHECK (released IN (0, 1))
);
CREATE INDEX IF NOT EXISTS idx_resource_authority_leases_active
    ON resource_authority_leases(released, resource_key);
CREATE INDEX IF NOT EXISTS idx_resource_authority_leases_live_order
    ON resource_authority_leases(lease_id) WHERE released=0;
CREATE TABLE IF NOT EXISTS resource_authority_tickets (
    ticket_id TEXT PRIMARY KEY,
    effect_id TEXT NOT NULL UNIQUE,
    realization_key TEXT NOT NULL,
    resource_key TEXT NOT NULL,
    provider_kind TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 1),
    spec_digest TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    holder_key TEXT NOT NULL,
    state TEXT NOT NULL CHECK (
        state IN ('prepared', 'bound', 'retiring', 'retired')
    )
);
CREATE INDEX IF NOT EXISTS idx_resource_authority_tickets_resource
    ON resource_authority_tickets(resource_key, generation, state);
CREATE INDEX IF NOT EXISTS idx_resource_authority_tickets_live_order
    ON resource_authority_tickets(ticket_id) WHERE state<>'retired';
CREATE TABLE IF NOT EXISTS resource_authority_single_flights (
    realization_key TEXT PRIMARY KEY,
    ticket_id TEXT NOT NULL UNIQUE,
    resource_key TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 1),
    holder_key TEXT NOT NULL,
    FOREIGN KEY(ticket_id) REFERENCES resource_authority_tickets(ticket_id)
);
CREATE TABLE IF NOT EXISTS resource_authority_bindings (
    resource_key TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation >= 1),
    ticket_id TEXT NOT NULL UNIQUE,
    spec_digest TEXT NOT NULL,
    provider_kind TEXT NOT NULL,
    physical_id TEXT NOT NULL,
    attributes_json TEXT NOT NULL,
    PRIMARY KEY(resource_key, generation),
    FOREIGN KEY(ticket_id) REFERENCES resource_authority_tickets(ticket_id)
);
CREATE INDEX IF NOT EXISTS idx_resource_authority_bindings_physical
    ON resource_authority_bindings(provider_kind, physical_id);
"""


RESOURCE_CLAIM_ADMISSION_COMPLEXITY = ComplexityContract(
    algorithm_id="resource.claim-admission.v4",
    implementation_digest=canonical_digest(
        ("resource.claim-admission.v4", "transactional-batched-aggregate-view")
    ),
    time_upper_bound=ComplexityBound.linear("candidate_footprint_total"),
    space_upper_bound=ComplexityBound.linear("candidate_unique_footprint"),
    assumptions=(
        "capacity and token usage aggregates are maintained transactionally",
        "candidate_footprint_total counts dimensions and shared/exclusive tokens actually examined before admission",
        "candidate_unique_footprint counts distinct dimensions/tokens across the candidate batch",
        "aggregate-state SQL reads are chunked by unique key rather than repeated per placement candidate",
    ),
    time_lower_bound=ComplexityBound.linear("candidate_footprint_total"),
)

RESOURCE_SNAPSHOT_FILTER_MATERIALIZATION_COMPLEXITY = ComplexityContract(
    algorithm_id="resource.snapshot-filter-materialization.v2",
    implementation_digest=canonical_digest(
        (
            "resource.snapshot-filter-materialization.v2",
            "unordered-in-parameter-materialization",
        )
    ),
    time_upper_bound=ComplexityBound.linear("resource_keys"),
    space_upper_bound=ComplexityBound.linear("resource_keys"),
    assumptions=(
        "resource_keys is already a unique set-like value",
        "SQL IN placeholder order is semantically irrelevant",
        "result canonical order is supplied by explicit SQL ORDER BY clauses",
    ),
    time_lower_bound=ComplexityBound.linear("resource_keys"),
    space_lower_bound=ComplexityBound.linear("resource_keys"),
)

def _execute_schema_locked(conn) -> None:
    """Execute schema DDL without sqlite3.executescript implicit commits."""

    statement = ""
    for line in _SCHEMA.splitlines():
        statement += line + "\n"
        if not sqlite3.complete_statement(statement):
            continue
        sql = statement.strip()
        statement = ""
        if sql:
            conn.execute(sql)
    if statement.strip():
        raise RuntimeError("resource Authority schema contains incomplete SQL")


RESOURCE_PHYSICAL_BINDING_LOOKUP_COMPLEXITY = ComplexityContract(
    algorithm_id="resource.physical-binding-lookup.v1",
    implementation_digest=canonical_digest(
        ("resource.physical-binding-lookup.v1", "sqlite-composite-btree")
    ),
    time_upper_bound=ComplexityBound.logarithmic("live_bindings"),
    space_upper_bound=ComplexityBound.constant(),
    assumptions=(
        "SQLite composite index on provider_kind and physical_id is available",
        "comparison-model B-tree point lookup",
    ),
    time_lower_bound=ComplexityBound.logarithmic("live_bindings"),
    space_lower_bound=ComplexityBound.constant(),
)


def _text(value: str, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value.strip()


def _scope_resource_key(scope: NoetriumUnit) -> str:
    if not is_scope_unit(scope):
        raise TypeError("scope authority resource requires scope Unit")
    return "scope:" + scope_key(scope)


def _encode_claim_projection(claim: NoetriumUnit) -> str:
    return json.dumps(
        {
            "projection": "resource-claim-scope-v1",
            "attributes": thaw_json(claim_field(claim, "attributes") or {}),
            "owner_scope": scope_to_data(claim_field(claim, "owner_scope")),
            "scope_generation": int(claim_field(claim, "scope_generation")),
            "scope_lease_id": claim_field(claim, "scope_lease_id"),
            "owner_lease_id": claim_field(claim, "owner_lease_id"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _decode_claim_projection(
    raw: object,
) -> tuple[dict[str, object], NoetriumUnit, int, str | None, str | None]:
    value = json.loads(str(raw))
    if not isinstance(value, dict) or value.get("projection") != "resource-claim-scope-v1":
        raise RuntimeError(
            "scope-less resource claim projection is incompatible with Authority v6"
        )
    attrs = value.get("attributes")
    if not isinstance(attrs, dict):
        raise RuntimeError("resource claim projection attributes are invalid")
    owner_scope = scope_from_data(value.get("owner_scope"))
    scope_generation = int(value.get("scope_generation"))
    scope_lease = value.get("scope_lease_id")
    if scope_lease is not None and (
        type(scope_lease) is not str or not scope_lease.strip()
    ):
        raise RuntimeError("resource claim projection scope lease is invalid")
    owner_lease = value.get("owner_lease_id")
    if owner_lease is not None and (
        type(owner_lease) is not str or not owner_lease.strip()
    ):
        raise RuntimeError("resource claim projection owner lease is invalid")
    return attrs, owner_scope, scope_generation, scope_lease, owner_lease


def _encode_lease_projection(lease: NoetriumUnit) -> str:
    return json.dumps(
        {
            "projection": "resource-lease-scope-v1",
            "metadata": thaw_json(lease_field(lease, "metadata") or {}),
            "owner_scope": scope_to_data(lease_field(lease, "owner_scope")),
            "scope_generation": int(lease_field(lease, "scope_generation")),
            "scope_lease_id": lease_field(lease, "scope_lease_id"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _decode_lease_projection(raw: object) -> tuple[dict[str, object], NoetriumUnit, int, str | None]:
    value = json.loads(str(raw))
    if not isinstance(value, dict) or value.get("projection") != "resource-lease-scope-v1":
        raise RuntimeError(
            "scope-less resource lease projection is incompatible with Authority v6"
        )
    metadata = value.get("metadata")
    if not isinstance(metadata, dict):
        raise RuntimeError("resource lease projection metadata is invalid")
    owner_scope = scope_from_data(value.get("owner_scope"))
    scope_generation = int(value.get("scope_generation"))
    scope_lease = value.get("scope_lease_id")
    if scope_lease is not None and (type(scope_lease) is not str or not scope_lease.strip()):
        raise RuntimeError("resource lease projection scope lease is invalid")
    return metadata, owner_scope, scope_generation, scope_lease


@dataclass(slots=True)
class _PendingClaimMutation:
    """One caller-owned barrier into a naturally coalesced Authority commit."""

    operation: str
    payload: object
    observed_at_epoch_s: float | None = None
    finished: Event = field(default_factory=Event)
    result: object | None = None
    failure: BaseException | None = None
    examined_candidates: int = 0


class UniversalResourceAuthority:
    """Sole durable dynamic truth for resource ownership and realization.

    Graphs remain the sole structural truth. Providers remain physical effects.
    This authority owns only linearizable dynamic facts: generation, claims,
    leases, single-flight tickets and realization bindings.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        timeout_seconds: float = 30.0,
        clock: LeaseClockPort | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        timeout = float(timeout_seconds)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError(
                "resource authority timeout_seconds must be finite and positive"
            )
        self.timeout_seconds = timeout
        # Exact-row decode interning. Claims and leases are immutable Units,
        # while their SQLite rows are versioned by the complete projected row.
        # Keep only the newest row observed for each durable identity: repeated
        # snapshots reuse the Unit in O(1), and renew/release replaces rather
        # than accumulates historical heartbeat versions.
        self._claim_decode_cache: dict[
            str, tuple[tuple[object, ...], NoetriumUnit]
        ] = {}
        self._lease_decode_cache: dict[
            str, tuple[tuple[object, ...], NoetriumUnit]
        ] = {}
        # Concurrent recovery requests for the same Authority cut collapse to
        # one scan/reproof. This is coordination only: durable ownership truth
        # remains exclusively in SQLite and later observation cuts re-run.
        self._orphan_reconcile_lock = Lock()
        self._orphan_reconciled_through_epoch_s = 0.0
        # One process-owned writer is the sole SQLite mutation lane for this
        # Authority. Reads remain independent snapshots and provider effects
        # execute outside this lane, so only linearizable metadata transitions
        # serialize.
        self._writers = DurableSQLiteWriterOwner(
            self.path,
            timeout_seconds=self.timeout_seconds,
        )
        # Model-slot admissions and releases are extremely short metadata
        # transitions but naturally arrive in bursts.  Preserve one global
        # linearization order while allowing already-concurrent callers to
        # share the same FULL-durable SQLite commit.  There is deliberately no
        # timer/batch window: the first caller drives the existing writer and
        # later callers join only if they are already queued before that writer
        # transaction takes its cut.
        self._claim_mutation_lock = Lock()
        self._claim_mutation_queue: deque[_PendingClaimMutation] = deque()
        self._claim_mutation_draining = False
        self._clock = LocalLeaseClock() if clock is None else clock
        if not isinstance(self._clock, LeaseClockPort):
            raise TypeError("resource authority requires LeaseClockPort")
        self._clock_domain: tuple[str, str, float, float] | None = None
        reading = self._clock.read()

        # Warm consumers attach read-only. A committed schema marker and a
        # same-host/same-boot clock anchor are a complete proof that no schema,
        # aggregate or fencing mutation is required. This avoids serializing
        # every paper/run behind SQLite BEGIN IMMEDIATE.
        if self._try_fast_attach(reading):
            return

        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="universal resource authority schema",
            ):
                _execute_schema_locked(conn)
                lease_columns = {
                    str(row[1])
                    for row in conn.execute(
                        "PRAGMA table_info(resource_authority_leases)"
                    ).fetchall()
                }
                if "acquired_at_epoch_s" not in lease_columns:
                    conn.execute(
                        "ALTER TABLE resource_authority_leases "
                        "ADD COLUMN acquired_at_epoch_s REAL"
                    )
                if "metadata_json" not in lease_columns:
                    conn.execute(
                        "ALTER TABLE resource_authority_leases "
                        "ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'"
                    )
                lease_scope_projection_added = False
                if "owner_scope_key" not in lease_columns:
                    conn.execute(
                        "ALTER TABLE resource_authority_leases "
                        "ADD COLUMN owner_scope_key TEXT"
                    )
                    lease_scope_projection_added = True
                if "scope_generation" not in lease_columns:
                    conn.execute(
                        "ALTER TABLE resource_authority_leases "
                        "ADD COLUMN scope_generation INTEGER"
                    )
                    lease_scope_projection_added = True
                if "scope_lease_id" not in lease_columns:
                    conn.execute(
                        "ALTER TABLE resource_authority_leases "
                        "ADD COLUMN scope_lease_id TEXT"
                    )
                    lease_scope_projection_added = True
                if lease_scope_projection_added:
                    rows = conn.execute(
                        "SELECT lease_id, metadata_json, released "
                        "FROM resource_authority_leases"
                    ).fetchall()
                    updates = []
                    for lease_id, metadata_json, released in rows:
                        try:
                            _metadata, owner_scope, scope_generation, scope_lease = (
                                _decode_lease_projection(metadata_json)
                            )
                        except (RuntimeError, TypeError, ValueError):
                            if not bool(released):
                                raise RuntimeError(
                                    "active scope-less resource lease is "
                                    "incompatible with Authority v7: "
                                    + str(lease_id)
                                )
                            continue
                        updates.append(
                            (
                                scope_key(owner_scope),
                                int(scope_generation),
                                scope_lease,
                                str(lease_id),
                            )
                        )
                    if updates:
                        conn.executemany(
                            "UPDATE resource_authority_leases SET "
                            "owner_scope_key=?, scope_generation=?, "
                            "scope_lease_id=? WHERE lease_id=?",
                            updates,
                        )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS "
                    "idx_resource_authority_leases_live_scope "
                    "ON resource_authority_leases("
                    "owner_scope_key, scope_generation, lease_id) "
                    "WHERE released=0"
                )
                claim_columns = {
                    str(row[1])
                    for row in conn.execute(
                        "PRAGMA table_info(resource_authority_claims)"
                    ).fetchall()
                }
                scope_projection_added = False
                if "owner_scope_key" not in claim_columns:
                    conn.execute(
                        "ALTER TABLE resource_authority_claims "
                        "ADD COLUMN owner_scope_key TEXT"
                    )
                    scope_projection_added = True
                if "scope_generation" not in claim_columns:
                    conn.execute(
                        "ALTER TABLE resource_authority_claims "
                        "ADD COLUMN scope_generation INTEGER"
                    )
                    scope_projection_added = True
                if "scope_lease_id" not in claim_columns:
                    conn.execute(
                        "ALTER TABLE resource_authority_claims "
                        "ADD COLUMN scope_lease_id TEXT"
                    )
                    scope_projection_added = True
                if "owner_lease_id" not in claim_columns:
                    conn.execute(
                        "ALTER TABLE resource_authority_claims "
                        "ADD COLUMN owner_lease_id TEXT"
                    )
                if scope_projection_added or "owner_lease_id" not in claim_columns:
                    rows = conn.execute(
                        "SELECT claim_id, attributes_json, released "
                        "FROM resource_authority_claims"
                    ).fetchall()
                    updates = []
                    for claim_id, attributes_json, released in rows:
                        try:
                            (
                                _attrs,
                                owner_scope,
                                scope_generation,
                                scope_lease,
                                owner_lease,
                            ) = _decode_claim_projection(attributes_json)
                        except (RuntimeError, TypeError, ValueError):
                            if not bool(released):
                                raise RuntimeError(
                                    "active scope-less resource claim is "
                                    "incompatible with Authority v7: "
                                    + str(claim_id)
                                )
                            continue
                        if (
                            scope_requires_live_lease(owner_scope)
                            and scope_lease is None
                            and not bool(released)
                        ):
                            raise RuntimeError(
                                "active dynamic-scope claim lacks canonical "
                                "scope lease in Authority v7: "
                                + str(claim_id)
                            )
                        updates.append(
                            (
                                scope_key(owner_scope),
                                int(scope_generation),
                                scope_lease,
                                owner_lease,
                                str(claim_id),
                            )
                        )
                    if updates:
                        conn.executemany(
                            "UPDATE resource_authority_claims SET "
                            "owner_scope_key=?, scope_generation=?, "
                            "scope_lease_id=?, owner_lease_id=? "
                            "WHERE claim_id=?",
                            updates,
                        )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS "
                    "idx_resource_authority_claims_active_scope_lease "
                    "ON resource_authority_claims(scope_lease_id, claim_id) "
                    "WHERE released=0 AND scope_lease_id IS NOT NULL"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS "
                    "idx_resource_authority_claims_active_owner "
                    "ON resource_authority_claims(owner_lease_id, claim_id) "
                    "WHERE released=0 AND owner_lease_id IS NOT NULL"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS "
                    "idx_resource_authority_claims_live_scope "
                    "ON resource_authority_claims("
                    "owner_scope_key, scope_generation, claim_id) "
                    "WHERE released=0"
                )
                self._ensure_claim_aggregate_locked(conn)

                ticket_columns = {
                    str(row[1])
                    for row in conn.execute(
                        "PRAGMA table_info(resource_authority_tickets)"
                    ).fetchall()
                }
                if "spec_json" not in ticket_columns:
                    # Historical tickets predate exact spec freezing. They remain
                    # observable/retirable but can never be replayed as PREPARED.
                    conn.execute(
                        "ALTER TABLE resource_authority_tickets "
                        "ADD COLUMN spec_json TEXT"
                    )
                self._bootstrap_event_ledger_locked(conn)
                platform_scope_key = _scope_resource_key(PLATFORM_SCOPE)
                platform_generation = self._generation_row(
                    conn,
                    platform_scope_key,
                )
                if platform_generation is None:
                    platform_generation = 1
                    conn.execute(
                        "INSERT INTO resource_authority_generations"
                        "(resource_key, generation) VALUES (?, ?)",
                        (platform_scope_key, platform_generation),
                    )
                    self._append_trace_event_locked(
                        conn,
                        resource_key=platform_scope_key,
                        generation=platform_generation,
                        subject=self._resource_event_subject(
                            platform_scope_key,
                            platform_generation,
                        ),
                        operation="generation",
                        phase="platform-root-bootstrap",
                        modality=TruthModality.AUTHORIZED,
                        writes=(
                            f"resource:{platform_scope_key}:generation",
                        ),
                    )
                self._clock_domain = self._resolve_clock_domain(
                    conn,
                    reading,
                )
                # Publish the proof last, in the same transaction as every
                # migration/derived aggregate and possible reboot fence.
                conn.execute(
                    "INSERT INTO resource_authority_meta(key,value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (_AUTHORITY_SCHEMA_META_KEY, _AUTHORITY_SCHEMA_VERSION),
                )

    def _connection(self):
        return self._writers.session()

    def _submit_claim_mutation(
        self,
        operation: str,
        payload: object,
        *,
        observed_at_epoch_s: float | None = None,
    ) -> object:
        pending = _PendingClaimMutation(
            operation=operation,
            payload=payload,
            observed_at_epoch_s=observed_at_epoch_s,
        )
        with self._claim_mutation_lock:
            lead = not self._claim_mutation_draining
            if lead:
                self._claim_mutation_draining = True
            else:
                self._claim_mutation_queue.append(pending)

        if lead:
            # Preserve the original one-operation/one-commit fast path when
            # there is no contention. Followers arriving while this durable
            # write is active are coalesced immediately afterwards; no batching
            # timer taxes solitary requests.
            try:
                pending.result = self._execute_claim_mutation_direct(pending)
            except BaseException as exc:
                pending.failure = exc

            if isinstance(pending.failure, sqlite3.Error):
                with self._claim_mutation_lock:
                    stranded = tuple(self._claim_mutation_queue)
                    self._claim_mutation_queue.clear()
                    self._claim_mutation_draining = False
                for item in stranded:
                    item.failure = pending.failure
                    item.finished.set()
            else:
                with self._claim_mutation_lock:
                    followers = bool(self._claim_mutation_queue)
                    if not followers:
                        self._claim_mutation_draining = False
                if followers:
                    self._drain_claim_mutations()
        else:
            pending.finished.wait()

        if pending.examined_candidates:
            add_cost_work(
                "resource_admission_candidates_examined",
                pending.examined_candidates,
            )
        if pending.failure is not None:
            raise pending.failure
        return pending.result

    def _execute_claim_mutation_direct(
        self, pending: _PendingClaimMutation,
    ) -> object:
        """Execute one solitary mutation on the pre-grouping hot path."""
        if pending.operation == "admit_bundle":
            if pending.observed_at_epoch_s is None:
                raise RuntimeError("resource admission lost authority clock cut")
            groups = pending.payload
            if type(groups) is tuple and len(groups) == 1:
                # Single logical group is the dominant model-admission shape.
                # Reuse the original admission transaction exactly, including
                # the caller's pre-writer TTL observation cut.
                return (
                    self._admit_first_at(
                        groups[0], pending.observed_at_epoch_s
                    ),
                )

        if pending.operation == "release_claim":
            with self._connection() as conn:
                with immediate_sqlite_transaction(
                    conn,
                    timeout_seconds=self.timeout_seconds,
                    label="resource claim release",
                ):
                    return self._release_claim_locked(
                        conn, str(pending.payload)
                    )

        # Multi-group bundles remain rare but must preserve exact all-or-none
        # semantics. They use the shared core without a SAVEPOINT because this
        # solitary operation already owns the outer transaction.
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource claim mutation",
            ):
                if pending.operation != "admit_bundle":
                    raise RuntimeError(
                        "unsupported resource claim mutation: " + pending.operation
                    )
                generation_rows: dict[str, int | None] = {}
                lease_rows: dict[str, NoetriumUnit | None] = {}
                orphan_valid_until: dict[str, float] = {}
                event_heads: dict[str, UnitRef | None] = {}
                capacity_rows: dict[str, int | None] = {}
                amount_usage_rows: dict[str, int] = {}
                return self._admit_bundle_locked(
                    conn,
                    pending.payload,
                    observed_at_epoch_s=pending.observed_at_epoch_s,
                    pending=pending,
                    generation_rows=generation_rows,
                    lease_rows=lease_rows,
                    orphan_valid_until=orphan_valid_until,
                    event_heads=event_heads,
                    capacity_rows=capacity_rows,
                    amount_usage_rows=amount_usage_rows,
                )

    def _drain_claim_mutations(self) -> None:
        """Commit naturally concurrent claim transitions in one writer cut.

        Each logical operation owns a SAVEPOINT, so a normal conflict/rejection
        rolls back only that caller while later queued operations still observe
        the exact preceding successful transitions.  A SQLite/transaction
        failure aborts the whole uncommitted batch.  Receipts are published only
        after the outer FULL-durable commit has completed.
        """
        while True:
            batch: list[_PendingClaimMutation] = []
            try:
                # Acquire the physical writer before taking the queue cut.
                # Threads that arrived while this caller was waiting therefore
                # join this commit without any artificial batching delay.
                with self._connection() as conn:
                    with immediate_sqlite_transaction(
                        conn,
                        timeout_seconds=self.timeout_seconds,
                        label="resource claim mutation group",
                    ):
                        generation_rows: dict[str, int | None] = {}
                        lease_rows: dict[str, NoetriumUnit | None] = {}
                        orphan_valid_until: dict[str, float] = {}
                        event_heads: dict[str, UnitRef | None] = {}
                        capacity_rows: dict[str, int | None] = {}
                        amount_usage_rows: dict[str, int] = {}
                        # Keep absorbing work that arrives while useful SQL is
                        # already executing.  This is not a batching window: if
                        # the queue is empty at a cut we commit immediately.
                        # It simply avoids forcing naturally concurrent arrivals
                        # to pay another fsync while the current transaction is
                        # still open.
                        while True:
                            with self._claim_mutation_lock:
                                chunk = tuple(self._claim_mutation_queue)
                                self._claim_mutation_queue.clear()
                            if not chunk:
                                break
                            start_index = len(batch)
                            batch.extend(chunk)
                            for offset, item in enumerate(chunk):
                                savepoint = f"claim_mutation_{start_index + offset}"
                                conn.execute("SAVEPOINT " + savepoint)
                                try:
                                    if item.operation == "admit_bundle":
                                        if item.observed_at_epoch_s is None:
                                            raise RuntimeError(
                                                "grouped resource admission lost authority clock cut"
                                            )
                                        item.result = self._admit_bundle_locked(
                                            conn,
                                            item.payload,
                                            observed_at_epoch_s=item.observed_at_epoch_s,
                                            pending=item,
                                            generation_rows=generation_rows,
                                            lease_rows=lease_rows,
                                            orphan_valid_until=orphan_valid_until,
                                            event_heads=event_heads,
                                            capacity_rows=capacity_rows,
                                            amount_usage_rows=amount_usage_rows,
                                        )
                                    elif item.operation == "release_claim":
                                        item.result = self._release_claim_locked(
                                            conn,
                                            str(item.payload),
                                            event_heads=event_heads,
                                            amount_usage_rows=amount_usage_rows,
                                        )
                                    else:
                                        raise RuntimeError(
                                            "unsupported grouped resource mutation: "
                                            + item.operation
                                        )
                                except sqlite3.Error:
                                    # The physical writer/transaction is suspect;
                                    # preserve fail-closed semantics for every
                                    # uncommitted caller in this cut.
                                    raise
                                except Exception as exc:
                                    conn.execute("ROLLBACK TO SAVEPOINT " + savepoint)
                                    conn.execute("RELEASE SAVEPOINT " + savepoint)
                                    item.result = None
                                    item.failure = exc
                                else:
                                    conn.execute("RELEASE SAVEPOINT " + savepoint)
            except BaseException as exc:
                # Nothing from `batch` committed.  Calls that arrived while the
                # failed writer was active cannot safely infer a later cut, so
                # fail them together rather than strand a waiter or retry behind
                # a potentially unhealthy Authority connection.
                with self._claim_mutation_lock:
                    stranded = tuple(self._claim_mutation_queue)
                    self._claim_mutation_queue.clear()
                    self._claim_mutation_draining = False
                for item in (*tuple(batch), *stranded):
                    item.result = None
                    item.failure = exc
                    item.finished.set()
                return
            else:
                # The transaction context has committed durably before any
                # caller observes success or a logical rejection from this cut.
                for item in batch:
                    item.finished.set()
                with self._claim_mutation_lock:
                    if self._claim_mutation_queue:
                        continue
                    self._claim_mutation_draining = False
                    return

    @staticmethod
    def _resource_event_domain(resource_key: str) -> str:
        key = _text(resource_key, "resource event key")
        return "resource." + canonical_digest(key)[:32]

    @staticmethod
    def _resource_event_subject(
        resource_key: str,
        generation: int,
    ) -> NoetriumUnit:
        key = _text(resource_key, "resource event subject")
        if type(generation) is not int or generation < 0:
            raise ValueError("resource event generation must be non-negative")
        return NoetriumUnit(
            "resource.subject:" + canonical_digest((key, generation)),
            schemas=("resource.subject",),
            attributes={
                "kind": "resource.subject",
                "resource_key": key,
                "generation": generation,
            },
        )

    @staticmethod
    def _event_head_ref_locked(
        conn,
        authority_domain: str,
        event_heads: dict[str, UnitRef | None] | None = None,
    ) -> UnitRef | None:
        if event_heads is not None and authority_domain in event_heads:
            return event_heads[authority_domain]
        row = conn.execute(
            "SELECT event_digest FROM resource_authority_event_heads "
            "WHERE authority_domain=?",
            (authority_domain,),
        ).fetchone()
        ref = None if row is None else UnitRef(("event:" + str(row[0]),))
        if event_heads is not None:
            event_heads[authority_domain] = ref
        return ref

    def _append_trace_event_locked(
        self,
        conn,
        *,
        resource_key: str,
        generation: int,
        subject: NoetriumUnit,
        operation: str,
        phase: str,
        modality: TruthModality,
        authority_domain: str | None = None,
        reads: tuple[str, ...] = (),
        writes: tuple[str, ...] = (),
        evidence: tuple[NoetriumUnit, ...] = (),
        physical_effect: bool = False,
        parent_domains: tuple[str, ...] = (),
        attributes: Mapping[str, JsonValue] | None = None,
        event_heads: dict[str, UnitRef | None] | None = None,
    ) -> NoetriumUnit:
        resource = _text(resource_key, "resource event key")
        domain = (
            self._resource_event_domain(resource)
            if authority_domain is None
            else _text(authority_domain, "event authority domain")
        )
        parents: list[UnitRef] = []
        for parent_domain in (domain, *parent_domains):
            ref = self._event_head_ref_locked(
                conn, parent_domain, event_heads
            )
            if ref is not None and ref not in parents:
                parents.append(ref)
        event = causal_event(
            authority_domain=domain,
            generation=generation,
            subject=subject,
            operation=operation,
            phase=phase,
            modality=TruthModality(modality),
            causal_parents=tuple(parents),
            reads=reads,
            writes=writes,
            evidence=evidence,
            physical_effect=physical_effect,
            attributes=attributes,
        )
        payload = encode_unit(event)
        existing = conn.execute(
            "SELECT payload FROM resource_authority_events "
            "WHERE event_digest=?",
            (event.unit_digest,),
        ).fetchone()
        if existing is not None:
            decoded = decode_unit(bytes(existing[0]))
            if decoded != event:
                raise RuntimeError("resource event digest collision")
            return decoded
        conn.execute(
            "INSERT INTO resource_authority_events"
            "(event_digest, authority_domain, generation, modality, resource_key, payload) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                event.unit_digest,
                domain,
                generation,
                TruthModality(modality).value,
                resource,
                payload,
            ),
        )
        conn.execute(
            "INSERT INTO resource_authority_event_heads"
            "(authority_domain, event_digest, generation) VALUES (?, ?, ?) "
            "ON CONFLICT(authority_domain) DO UPDATE SET "
            "event_digest=excluded.event_digest, generation=excluded.generation",
            (domain, event.unit_digest, generation),
        )
        if event_heads is not None:
            event_heads[domain] = UnitRef(("event:" + event.unit_digest,))
        return event

    def _bootstrap_event_ledger_locked(self, conn) -> None:
        """Materialize one genesis trace for pre-event Authority projections.

        This is a migration boundary only. New v5 transitions always append an
        Event Unit in the same SQLite transaction as their disposable
        projection update.
        """

        row = conn.execute(
            "SELECT 1 FROM resource_authority_events LIMIT 1"
        ).fetchone()
        if row is not None:
            return
        has_projection = any(
            conn.execute("SELECT 1 FROM " + table + " LIMIT 1").fetchone()
            is not None
            for table in (
                "resource_authority_generations",
                "resource_authority_capacity",
                "resource_authority_claims",
                "resource_authority_leases",
                "resource_authority_tickets",
                "resource_authority_bindings",
            )
        )
        if not has_projection:
            return

        for resource_key, generation in conn.execute(
            "SELECT resource_key, generation "
            "FROM resource_authority_generations ORDER BY resource_key"
        ).fetchall():
            key = str(resource_key)
            value = int(generation)
            self._append_trace_event_locked(
                conn,
                resource_key=key,
                generation=value,
                subject=self._resource_event_subject(key, value),
                operation="generation",
                phase="bootstrap",
                modality=TruthModality.AUTHORIZED,
                writes=(f"resource:{key}:generation",),
            )

        for dimension, limit in conn.execute(
            "SELECT dimension, capacity FROM resource_authority_capacity "
            "ORDER BY dimension"
        ).fetchall():
            dimension = str(dimension)
            capacity_key = "capacity:" + dimension
            self._append_trace_event_locked(
                conn,
                resource_key=capacity_key,
                generation=1,
                subject=resource_capacity_fact(
                    dimension,
                    int(limit),
                    modality=TruthModality.AUTHORIZED,
                ),
                operation="capacity",
                phase="bootstrap",
                modality=TruthModality.AUTHORIZED,
                writes=(f"capacity:{dimension}",),
            )

        for row in conn.execute(
            "SELECT claim_id, resource_key, holder_key, generation, "
            "amounts_json, shared_json, exclusive_json, attributes_json, released "
            "FROM resource_authority_claims ORDER BY claim_id"
        ).fetchall():
            claim = self._decode_claim(row[:8])
            self._append_claim_event_locked(
                conn,
                claim,
                operation="release" if bool(row[8]) else "acquire",
                phase="bootstrap",
            )

        for row in conn.execute(
            "SELECT lease_id, resource_key, holder_key, generation, "
            "expires_at_epoch_s, acquired_at_epoch_s, metadata_json, released "
            "FROM resource_authority_leases ORDER BY lease_id"
        ).fetchall():
            lease = self._decode_lease(row)
            self._append_lease_event_locked(
                conn,
                lease,
                operation="release" if bool(row[7]) else "acquire",
                phase="bootstrap",
            )

        for row in conn.execute(
            "SELECT ticket_id, effect_id, realization_key, resource_key, "
            "provider_kind, generation, spec_digest, holder_key, state, spec_json "
            "FROM resource_authority_tickets ORDER BY ticket_id"
        ).fetchall():
            ticket = self._decode_ticket(row[:9])
            evidence: tuple[NoetriumUnit, ...] = ()
            if row[9] is not None:
                spec = self._decode_realization_spec(row[9])
                evidence = (
                    realization_spec_fact(
                        spec.provider_kind,
                        spec.parameters,
                        modality=TruthModality.DECLARED,
                    ),
                )
            self._append_ticket_event_locked(
                conn,
                ticket,
                operation="bootstrap",
                phase=ticket_field(ticket, "state").value,
                evidence=evidence,
            )

        for row in conn.execute(
            "SELECT resource_key, generation, ticket_id, spec_digest, "
            "provider_kind, physical_id, attributes_json "
            "FROM resource_authority_bindings "
            "ORDER BY resource_key, generation"
        ).fetchall():
            self._append_binding_event_locked(
                conn,
                self._decode_binding(row),
                operation="bind",
                phase="bootstrap",
            )

    def event_trace(
        self,
        *,
        resource_key: str | None = None,
        authority_domain: str | None = None,
    ) -> tuple[NoetriumUnit, ...]:
        if resource_key is not None and authority_domain is not None:
            raise ValueError("event trace accepts resource_key or authority_domain, not both")
        clause = ""
        params: tuple[str, ...] = ()
        if resource_key is not None:
            clause = " WHERE resource_key=?"
            params = (_text(resource_key, "resource event key"),)
        elif authority_domain is not None:
            clause = " WHERE authority_domain=?"
            params = (_text(authority_domain, "event authority domain"),)
        with self._reader() as conn:
            rows = conn.execute(
                "SELECT payload FROM resource_authority_events"
                + clause
                + " ORDER BY authority_domain, event_digest",
                params,
            ).fetchall()
        return tuple(decode_unit(bytes(row[0])) for row in rows)


    @staticmethod
    def project_snapshot_from_events(
        events: tuple[NoetriumUnit, ...],
    ) -> AuthoritySnapshot:
        """Pure rebuild of the live Authority view from causal Event Units.

        The fold uses event semantics only. SQLite tables are not consulted.
        Independent authority domains may appear in any topological order.
        """

        ordered = causal_topological_order(events)
        generations: dict[str, AuthorityGeneration] = {}
        claims: dict[str, NoetriumUnit] = {}
        leases: dict[str, NoetriumUnit] = {}
        tickets: dict[str, NoetriumUnit] = {}
        bindings: dict[tuple[str, int], NoetriumUnit] = {}

        for event in ordered:
            if event_field(event, "modality") is not TruthModality.AUTHORIZED:
                continue
            subject = event_field(event, "subject")
            if type(subject) is not NoetriumUnit:
                continue
            operation = str(event_field(event, "operation"))
            phase = str(event_field(event, "phase"))

            event_attributes = event_field(event, "event_attributes")
            if (
                operation == "renew"
                and isinstance(event_attributes, Mapping)
                and event_attributes.get("delta_kind") == "lease-expiry"
            ):
                lease_id = str(event_attributes.get("lease_id") or "").strip()
                expiry = event_attributes.get("expires_at_epoch_s")
                if not lease_id or not isinstance(expiry, (int, float)):
                    raise RuntimeError(
                        "lease renewal Event has invalid canonical delta"
                    )
                current = leases.get(lease_id)
                if current is None:
                    raise RuntimeError(
                        "lease renewal Event has no prior acquired lease: "
                        + lease_id
                    )
                if not subject.has_schema("resource.subject"):
                    raise RuntimeError(
                        "lease renewal Event lost resource subject"
                    )
                resource_key = str(subject.attribute("resource_key"))
                generation = int(subject.attribute("generation"))
                if (
                    str(lease_field(current, "resource_key"))
                    != resource_key
                    or int(lease_field(current, "generation"))
                    != generation
                ):
                    raise RuntimeError(
                        "lease renewal Event crossed resource generation: "
                        + lease_id
                    )
                leases[lease_id] = authority_lease(
                    lease_id=lease_id,
                    resource_key=resource_key,
                    holder_key=str(lease_field(current, "holder_key")),
                    generation=generation,
                    owner_scope=lease_field(current, "owner_scope"),
                    scope_generation=int(
                        lease_field(current, "scope_generation")
                    ),
                    scope_lease_id=lease_field(
                        current,
                        "scope_lease_id",
                    ),
                    expires_at_epoch_s=float(expiry),
                    released=False,
                    acquired_at_epoch_s=lease_field(
                        current,
                        "acquired_at_epoch_s",
                    ),
                    metadata=lease_field(current, "metadata"),
                    modality=TruthModality.AUTHORIZED,
                )
                continue

            if subject.has_schema("resource.subject"):
                resource_key = str(subject.attribute("resource_key"))
                generation = int(subject.attribute("generation"))
                generations[resource_key] = AuthorityGeneration(
                    resource_key,
                    generation,
                )
                continue

            if is_resource_capacity_fact(subject):
                continue

            if is_resource_claim(subject):
                claim_id = str(claim_field(subject, "claim_id"))
                if operation == "release":
                    claims.pop(claim_id, None)
                else:
                    claims[claim_id] = subject
                continue

            if is_authority_lease(subject):
                lease_id = str(lease_field(subject, "lease_id"))
                if bool(lease_field(subject, "released")) or operation == "release":
                    leases.pop(lease_id, None)
                else:
                    leases[lease_id] = subject
                continue

            if is_realization_ticket(subject):
                ticket_id = str(ticket_field(subject, "ticket_id"))
                if ticket_field(subject, "state") is TicketState.RETIRED:
                    tickets.pop(ticket_id, None)
                else:
                    tickets[ticket_id] = subject
                continue

            if is_realization_binding(subject):
                key = (
                    str(binding_field(subject, "resource_key")),
                    int(binding_field(subject, "generation")),
                )
                if operation == "retire" or phase == "retired":
                    bindings.pop(key, None)
                else:
                    bindings[key] = subject
                continue

        # A retired ticket invalidates its binding even when retirement emits
        # only the ticket Unit. This is a deterministic projection rule, not a
        # second truth source.
        live_ticket_ids = set(tickets)
        bindings = {
            key: binding
            for key, binding in bindings.items()
            if str(binding_field(binding, "ticket_id")) in live_ticket_ids
        }

        return AuthoritySnapshot(
            generations=tuple(
                generations[key] for key in sorted(generations)
            ),
            claims=tuple(
                claims[key] for key in sorted(claims)
            ),
            leases=tuple(
                leases[key] for key in sorted(leases)
            ),
            tickets=tuple(
                tickets[key] for key in sorted(tickets)
            ),
            bindings=tuple(
                bindings[key] for key in sorted(bindings)
            ),
        )

    def verify_projection_rebuild(self) -> AuthoritySnapshot:
        """Fail-close unless every semantic projection is a Journal fold."""

        events = self.event_trace()
        projected = self.project_snapshot_from_events(events)
        materialized = self.snapshot()
        if projected != materialized:
            raise RuntimeError(
                "resource Authority projection diverged from Unit/Event Journal"
            )

        capacity_limits: dict[str, int] = {}
        realization_specs: dict[str, NoetriumUnit] = {}
        for event in causal_topological_order(events):
            subject = event_field(event, "subject")
            if type(subject) is not NoetriumUnit:
                continue
            if is_resource_capacity_fact(subject):
                capacity_limits[
                    str(capacity_field(subject, "dimension"))
                ] = int(capacity_field(subject, "limit"))
                continue
            if not is_realization_ticket(subject):
                continue
            ticket_id = str(ticket_field(subject, "ticket_id"))
            for evidence in event_field(event, "evidence"):
                if (
                    type(evidence) is NoetriumUnit
                    and is_realization_spec_fact(evidence)
                ):
                    realization_specs[ticket_id] = evidence

        with self._reader() as conn:
            materialized_capacity = self._capacity(conn)
            spec_rows = conn.execute(
                "SELECT ticket_id, spec_json "
                "FROM resource_authority_tickets ORDER BY ticket_id"
            ).fetchall()
        projected_capacity = ResourceCapacity(
            tuple(sorted(capacity_limits.items()))
        )
        if projected_capacity != materialized_capacity:
            raise RuntimeError(
                "resource capacity projection diverged from Unit/Event Journal"
            )
        for ticket_id, spec_json in spec_rows:
            if spec_json is None:
                continue
            persisted = self._decode_realization_spec(spec_json)
            evidence = realization_specs.get(str(ticket_id))
            if evidence is None:
                raise RuntimeError(
                    "resource realization spec cannot be rebuilt from Journal: "
                    + str(ticket_id)
                )
            if (
                realization_spec_field(evidence, "provider_kind")
                != persisted.provider_kind
                or dict(realization_spec_field(evidence, "parameters") or {})
                != dict(persisted.parameters or {})
            ):
                raise RuntimeError(
                    "resource realization spec projection diverged from Journal: "
                    + str(ticket_id)
                )
        return projected

    @staticmethod
    def _authorized_claim(claim: NoetriumUnit) -> NoetriumUnit:
        if not is_resource_claim(claim):
            raise TypeError("authorized claim projection requires resource.claim Unit")
        if truth_modality(claim) is TruthModality.AUTHORIZED:
            return claim
        return resource_claim(
            claim_id=claim_field(claim, "claim_id"),
            resource_key=claim_field(claim, "resource_key"),
            holder_key=claim_field(claim, "holder_key"),
            generation=claim_field(claim, "generation"),
            owner_scope=claim_field(claim, "owner_scope"),
            scope_generation=claim_field(claim, "scope_generation"),
            scope_lease_id=claim_field(claim, "scope_lease_id"),
            owner_lease_id=claim_field(claim, "owner_lease_id"),
            amounts=tuple(claim_field(claim, "amounts")),
            shared=tuple(claim_field(claim, "shared")),
            exclusive=tuple(claim_field(claim, "exclusive")),
            attributes=claim_field(claim, "attributes"),
            modality=TruthModality.AUTHORIZED,
        )

    @staticmethod
    def _authorized_lease(
        lease: NoetriumUnit,
        *,
        released: bool | None = None,
        expires_at_epoch_s: float | None | object = ...,
    ) -> NoetriumUnit:
        if not is_authority_lease(lease):
            raise TypeError("authorized lease projection requires resource.lease Unit")
        current_expiry = lease_field(lease, "expires_at_epoch_s")
        current_released = bool(lease_field(lease, "released"))
        expiry = (
            current_expiry
            if expires_at_epoch_s is ...
            else expires_at_epoch_s
        )
        effective_released = current_released if released is None else released
        if (
            truth_modality(lease) is TruthModality.AUTHORIZED
            and expiry == current_expiry
            and bool(effective_released) == current_released
        ):
            return lease
        return authority_lease(
            lease_id=lease_field(lease, "lease_id"),
            resource_key=lease_field(lease, "resource_key"),
            holder_key=lease_field(lease, "holder_key"),
            generation=lease_field(lease, "generation"),
            owner_scope=lease_field(lease, "owner_scope"),
            scope_generation=lease_field(lease, "scope_generation"),
            scope_lease_id=lease_field(lease, "scope_lease_id"),
            expires_at_epoch_s=expiry,
            released=bool(effective_released),
            acquired_at_epoch_s=lease_field(lease, "acquired_at_epoch_s"),
            metadata=lease_field(lease, "metadata"),
            modality=TruthModality.AUTHORIZED,
        )

    def _append_claim_event_locked(
        self,
        conn,
        claim: NoetriumUnit,
        *,
        operation: str,
        phase: str,
        event_heads: dict[str, UnitRef | None] | None = None,
    ) -> NoetriumUnit:
        authorized = self._authorized_claim(claim)
        resource = str(claim_field(authorized, "resource_key"))
        generation = int(claim_field(authorized, "generation"))
        claim_id = str(claim_field(authorized, "claim_id"))
        return self._append_trace_event_locked(
            conn,
            resource_key=resource,
            generation=generation,
            subject=authorized,
            operation=operation,
            phase=phase,
            modality=TruthModality.AUTHORIZED,
            reads=tuple(
                f"capacity:{dimension}"
                for dimension, _amount in claim_field(authorized, "amounts")
            ),
            writes=(
                f"resource:{resource}:claim:{claim_id}",
                f"resource:{resource}:generation:{generation}",
            ),
            event_heads=event_heads,
        )

    def _append_lease_event_locked(
        self,
        conn,
        lease: NoetriumUnit,
        *,
        operation: str,
        phase: str,
    ) -> NoetriumUnit:
        authorized = self._authorized_lease(lease)
        resource = str(lease_field(authorized, "resource_key"))
        generation = int(lease_field(authorized, "generation"))
        lease_id = str(lease_field(authorized, "lease_id"))
        return self._append_trace_event_locked(
            conn,
            resource_key=resource,
            generation=generation,
            subject=authorized,
            operation=operation,
            phase=phase,
            modality=TruthModality.AUTHORIZED,
            reads=(f"resource:{resource}:generation:{generation}",),
            writes=(f"resource:{resource}:lease:{lease_id}",),
        )

    def _append_lease_renewal_event_locked(
        self,
        conn,
        lease: NoetriumUnit,
    ) -> NoetriumUnit:
        """Append one minimal lease-expiry delta Event."""

        authorized = self._authorized_lease(lease)
        resource = str(lease_field(authorized, "resource_key"))
        generation = int(lease_field(authorized, "generation"))
        lease_id = str(lease_field(authorized, "lease_id"))
        expiry = lease_field(authorized, "expires_at_epoch_s")
        if expiry is None:
            raise ValueError(
                "lease renewal journal delta requires finite expiry"
            )
        return self._append_trace_event_locked(
            conn,
            resource_key=resource,
            generation=generation,
            subject=self._resource_event_subject(resource, generation),
            operation="renew",
            phase="committed",
            modality=TruthModality.AUTHORIZED,
            reads=(
                f"resource:{resource}:generation:{generation}",
                f"resource:{resource}:lease:{lease_id}",
            ),
            writes=(f"resource:{resource}:lease:{lease_id}:expiry",),
            attributes={
                "delta_kind": "lease-expiry",
                "lease_id": lease_id,
                "expires_at_epoch_s": float(expiry),
            },
        )

    def _append_ticket_event_locked(
        self,
        conn,
        ticket: NoetriumUnit,
        *,
        operation: str,
        phase: str,
        evidence: tuple[NoetriumUnit, ...] = (),
    ) -> NoetriumUnit:
        resource = str(ticket_field(ticket, "resource_key"))
        generation = int(ticket_field(ticket, "generation"))
        ticket_id = str(ticket_field(ticket, "ticket_id"))
        return self._append_trace_event_locked(
            conn,
            resource_key=resource,
            generation=generation,
            subject=ticket,
            operation=operation,
            phase=phase,
            modality=TruthModality.AUTHORIZED,
            reads=(f"resource:{resource}:generation:{generation}",),
            writes=(f"resource:{resource}:ticket:{ticket_id}",),
            evidence=evidence,
        )

    def _append_binding_event_locked(
        self,
        conn,
        binding: NoetriumUnit,
        *,
        operation: str,
        phase: str,
    ) -> NoetriumUnit:
        resource = str(binding_field(binding, "resource_key"))
        generation = int(binding_field(binding, "generation"))
        ticket_id = str(binding_field(binding, "ticket_id"))
        return self._append_trace_event_locked(
            conn,
            resource_key=resource,
            generation=generation,
            subject=binding,
            operation=operation,
            phase=phase,
            modality=TruthModality.AUTHORIZED,
            reads=(f"resource:{resource}:ticket:{ticket_id}",),
            writes=(f"resource:{resource}:binding:{generation}",),
        )

    @staticmethod
    def _observation_event_domain(
        resource_key: str,
        ticket_id: str,
        provider_kind: str,
    ) -> str:
        return "provider." + canonical_digest(
            (resource_key, ticket_id, provider_kind)
        )[:32]

    def _append_observation_event_locked(
        self,
        conn,
        observation: NoetriumUnit,
    ) -> NoetriumUnit:
        if not is_resource_observation(observation):
            raise TypeError("resource observation event requires resource.observation Unit")
        resource = str(observation_field(observation, "resource_key"))
        generation = int(observation_field(observation, "generation"))
        ticket_id = str(observation_field(observation, "ticket_id"))
        identity = observation_field(observation, "physical_identity")
        provider_kind = (
            "absent"
            if identity is None
            else str(physical_field(identity, "provider_kind"))
        )
        # Absent observations still belong to the ticket provider domain. Resolve
        # the frozen ticket when possible so one ticket has one causal provider
        # chain across present -> absent transitions.
        if identity is None:
            try:
                ticket = self._ticket(conn, ticket_id)
            except KeyError:
                ticket = None
            if ticket is not None:
                provider_kind = str(ticket_field(ticket, "provider_kind"))
        domain = self._observation_event_domain(
            resource, ticket_id, provider_kind
        )
        return self._append_trace_event_locked(
            conn,
            resource_key=resource,
            generation=generation,
            subject=observation,
            operation="observe",
            phase="sampled",
            modality=TruthModality.OBSERVED,
            authority_domain=domain,
            reads=(f"physical:{resource}:{generation}",),
            writes=(),
            evidence=(),
            physical_effect=True,
            parent_domains=(self._resource_event_domain(resource),),
        )

    def record_observation(self, observation: NoetriumUnit) -> NoetriumUnit:
        if not is_resource_observation(observation):
            raise TypeError("resource observation journal requires resource.observation Unit")
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource observation journal",
            ):
                return self._append_observation_event_locked(conn, observation)

    def _latest_observation_for_ticket(
        self,
        ticket: NoetriumUnit,
    ) -> NoetriumUnit | None:
        if not is_realization_ticket(ticket):
            raise TypeError("latest observation lookup requires realization ticket")
        domain = self._observation_event_domain(
            str(ticket_field(ticket, "resource_key")),
            str(ticket_field(ticket, "ticket_id")),
            str(ticket_field(ticket, "provider_kind")),
        )
        with self._reader() as conn:
            row = conn.execute(
                "SELECT e.payload FROM resource_authority_event_heads h "
                "JOIN resource_authority_events e "
                "ON e.event_digest=h.event_digest "
                "WHERE h.authority_domain=?",
                (domain,),
            ).fetchone()
        if row is None:
            return None
        event = decode_unit(bytes(row[0]))
        subject = event_field(event, "subject")
        if not is_resource_observation(subject):
            raise RuntimeError(
                "provider event head is not a resource observation"
            )
        self._validate_observation(ticket, subject)
        return subject

    def _provider_reference(
        self,
        ticket: NoetriumUnit,
        snapshot: AuthoritySnapshot,
    ) -> NoetriumUnit:
        latest = self._latest_observation_for_ticket(ticket)
        if latest is not None:
            identity = observation_field(latest, "physical_identity")
            if identity is not None:
                return identity
        binding = snapshot.binding_for(str(ticket_field(ticket, "resource_key")))
        if binding is not None and binding_field(binding, "ticket_id") == ticket_field(ticket, "ticket_id"):
            return binding_field(binding, "physical_identity")
        return ticket

    def _retire_ticket_for_lost_ownership(
        self,
        *,
        ticket: NoetriumUnit,
        provider: PhysicalResourceProvider,
        snapshot: AuthoritySnapshot,
        reference: NoetriumUnit | None = None,
    ) -> None:
        ticket_id = str(ticket_field(ticket, "ticket_id"))
        retiring = self.begin_retire(ticket_id)
        physical_reference = (
            self._provider_reference(retiring, snapshot)
            if reference is None
            else reference
        )
        observation = provider.retire(physical_reference, retiring)
        self._validate_observation(retiring, observation)
        if observation_field(observation, "exists"):
            self.record_observation(observation)
            return
        self.complete_retire(ticket_id, observation)
        self.reconcile_orphan_claims()

    def close(self) -> None:
        self._writers.close()

    def _reader(self):
        return durable_sqlite_reader(
            self.path,
            timeout_seconds=self.timeout_seconds,
        )

    @staticmethod
    def _decode_clock_anchor_value(
        value: object,
    ) -> tuple[str, str, float, float]:
        try:
            payload = json.loads(str(value))
            host = str(payload["host_identity_digest"])
            boot = str(payload["boot_identity_digest"])
            anchor_elapsed = float(payload["elapsed_seconds"])
            anchor_epoch = float(payload["logical_epoch_seconds"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                "resource authority durable lease clock anchor is malformed"
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
            raise RuntimeError(
                "resource authority durable lease clock anchor is invalid"
            )
        return (host, boot, anchor_elapsed, anchor_epoch)

    def _try_fast_attach(self, reading: LeaseClockReading) -> bool:
        if not isinstance(reading, LeaseClockReading):
            raise TypeError("resource authority lease clock returned invalid reading")
        if not self.path.is_file():
            return False
        try:
            with self._reader() as conn:
                marker = conn.execute(
                    "SELECT value FROM resource_authority_meta WHERE key=?",
                    (_AUTHORITY_SCHEMA_META_KEY,),
                ).fetchone()
                if marker is None or str(marker[0]) != _AUTHORITY_SCHEMA_VERSION:
                    return False
                row = conn.execute(
                    "SELECT value FROM resource_authority_meta WHERE key=?",
                    (self._LEASE_CLOCK_ANCHOR_KEY,),
                ).fetchone()
        except Exception as exc:
            # Missing/pre-current schema must converge through the writer path.
            # Corruption/IO errors on a current-looking database must not be
            # silently treated as a valid warm attachment.
            import sqlite3
            if isinstance(exc, sqlite3.OperationalError):
                return False
            raise
        if row is None:
            return False
        host, boot, anchor_elapsed, anchor_epoch = (
            self._decode_clock_anchor_value(row[0])
        )
        if host != reading.host_identity_digest:
            raise RuntimeError(
                "resource authority belongs to a different host clock domain"
            )
        if boot != reading.boot_identity_digest:
            # Reboot is a universal fencing mutation and must serialize through
            # the writer path so all generations advance atomically.
            return False
        if reading.elapsed_seconds < anchor_elapsed:
            raise RuntimeError(
                "same-boot suspend-aware lease clock moved backwards"
            )
        self._clock_domain = (host, boot, anchor_elapsed, anchor_epoch)
        return True

    @staticmethod
    def _generation_row(
        conn,
        resource_key: str,
        generation_rows: dict[str, int | None] | None = None,
    ) -> int | None:
        if generation_rows is not None and resource_key in generation_rows:
            return generation_rows[resource_key]
        row = conn.execute(
            "SELECT generation FROM resource_authority_generations "
            "WHERE resource_key=?",
            (resource_key,),
        ).fetchone()
        current = None if row is None else int(row[0])
        if generation_rows is not None:
            generation_rows[resource_key] = current
        return current

    @classmethod
    def _require_generation(
        cls,
        conn,
        resource_key: str,
        generation: int,
        *,
        generation_rows: dict[str, int | None] | None = None,
    ) -> None:
        current = cls._generation_row(conn, resource_key, generation_rows)
        if current is None or current != generation:
            raise RuntimeError(
                f"resource generation is fenced: resource={resource_key} "
                f"expected={generation} current={current}"
            )

    def _ensure_generations(
        self,
        resource_keys: tuple[str, ...],
    ) -> tuple[AuthorityGeneration, ...]:
        keys = tuple(_text(key, "resource key") for key in resource_keys)
        if not keys:
            return ()
        unique_keys = tuple(dict.fromkeys(keys))

        def read_generations(conn) -> dict[str, int]:
            values: dict[str, int] = {}
            for chunk in self._chunked_keys(unique_keys):
                placeholders = ",".join("?" for _ in chunk)
                values.update(
                    (str(key), int(generation))
                    for key, generation in conn.execute(
                        "SELECT resource_key, generation "
                        "FROM resource_authority_generations "
                        f"WHERE resource_key IN ({placeholders})",
                        chunk,
                    ).fetchall()
                )
            return values

        # Existing generations are read-mostly and need no writer.
        with self._reader() as conn:
            values = read_generations(conn)
        if len(values) != len(unique_keys):
            with self._connection() as conn:
                with immediate_sqlite_transaction(
                    conn,
                    timeout_seconds=self.timeout_seconds,
                    label="resource generation ensure",
                ):
                    # Re-read under the writer cut so concurrent creation or
                    # fencing wins before missing generations are established.
                    values = read_generations(conn)
                    for key in unique_keys:
                        if key in values:
                            continue
                        conn.execute(
                            "INSERT INTO resource_authority_generations"
                            "(resource_key, generation) VALUES (?, 1)",
                            (key,),
                        )
                        values[key] = 1
                        self._append_trace_event_locked(
                            conn,
                            resource_key=key,
                            generation=1,
                            subject=self._resource_event_subject(key, 1),
                            operation="generation",
                            phase="ensured",
                            modality=TruthModality.AUTHORIZED,
                            writes=(f"resource:{key}:generation",),
                        )
        return tuple(AuthorityGeneration(key, values[key]) for key in keys)

    def ensure_generations(
        self,
        resource_keys: tuple[str, ...],
    ) -> tuple[AuthorityGeneration, ...]:
        """Ensure many independent generation rows through one Authority cut."""
        return self._ensure_generations(resource_keys)

    def ensure_generation(self, resource_key: str) -> AuthorityGeneration:
        return self.ensure_generations((resource_key,))[0]

    def ensure_scope_generation(
        self,
        scope: NoetriumUnit,
    ) -> AuthorityGeneration:
        if not is_scope_unit(scope):
            raise TypeError("scope generation requires scope Unit")
        return self.ensure_generation(_scope_resource_key(scope))

    def scope_ownership_cut(
        self,
        scope: NoetriumUnit,
        *,
        scope_lease: NoetriumUnit | None = None,
    ) -> tuple[AuthorityGeneration, str | None]:
        """Resolve the current Authority cut for one ownership scope."""

        generation = self.ensure_scope_generation(scope)
        if not scope_requires_live_lease(scope):
            if scope_lease is not None:
                raise ValueError(
                    "static scope ownership must not carry a scope lease"
                )
            return generation, None
        if not is_authority_lease(scope_lease):
            raise ResourceClaimConflict(
                "dynamic scope ownership requires canonical live scope lease: "
                + scope_key(scope)
            )
        lease_id = str(lease_field(scope_lease, "lease_id"))
        observed_at = self._lease_now(None)
        with self._reader() as conn:
            self._require_live_scope_lease_locked(
                conn,
                owner_scope=scope,
                scope_generation=generation.generation,
                scope_lease_id=lease_id,
                observed_at_epoch_s=observed_at,
            )
        return generation, lease_id

    def acquire_scope_lease(
        self,
        *,
        scope: NoetriumUnit,
        parent_scope: NoetriumUnit,
        holder_key: str,
        ttl_seconds: float,
        parent_scope_lease: NoetriumUnit | None = None,
        now: float | None = None,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> NoetriumUnit:
        """Acquire the canonical liveness lease for one dynamic scope."""

        if not is_scope_unit(scope) or not is_scope_unit(parent_scope):
            raise TypeError("scope lease acquisition requires scope Units")
        if not scope_requires_live_lease(scope):
            raise ValueError(
                "static scope does not require canonical liveness lease: "
                + scope_key(scope)
            )
        validate_scope_parent(scope, parent_scope)
        payload = {} if metadata is None else dict(metadata)
        if "kind" in payload or "scope" in payload:
            raise ValueError(
                "scope lease metadata cannot override canonical fields"
            )
        payload.update(
            {
                "kind": "scope-lifetime",
                "scope": scope_to_data(scope),
            }
        )
        return self.acquire_exclusive_ttl_lease(
            lease_id="scope-lifetime:"
            + canonical_digest(
                {
                    "scope": scope.unit_digest,
                    "holder_key": _text(holder_key, "scope lease holder"),
                }
            ),
            resource_key=_scope_resource_key(scope),
            holder_key=holder_key,
            owner_scope=parent_scope,
            scope_lease=parent_scope_lease,
            ttl_seconds=ttl_seconds,
            now=now,
            metadata=payload,
        )

    def generation(self, resource_key: str) -> AuthorityGeneration | None:
        key = _text(resource_key, "resource key")
        with self._reader() as conn:
            row = self._generation_row(conn, key)
        return None if row is None else AuthorityGeneration(key, row)

    def advance_generation(self, resource_key: str) -> AuthorityGeneration:
        key = _text(resource_key, "resource key")
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource generation fence",
            ):
                current = self._generation_row(conn, key)
                next_generation = 1 if current is None else current + 1
                conn.execute(
                    "INSERT INTO resource_authority_generations"
                    "(resource_key, generation) VALUES (?, ?) "
                    "ON CONFLICT(resource_key) DO UPDATE SET generation=excluded.generation",
                    (key, next_generation),
                )
                conn.execute(
                    "DELETE FROM resource_authority_single_flights "
                    "WHERE resource_key=? AND generation<>?",
                    (key, next_generation),
                )
                self._append_trace_event_locked(
                    conn,
                    resource_key=key,
                    generation=next_generation,
                    subject=self._resource_event_subject(key, next_generation),
                    operation="fence",
                    phase="advanced",
                    modality=TruthModality.AUTHORIZED,
                    reads=(f"resource:{key}:generation",),
                    writes=(f"resource:{key}:generation",),
                )
                return AuthorityGeneration(key, next_generation)

    def _capacity_values(
        self,
        conn,
        dimensions: tuple[str, ...],
    ) -> dict[str, int]:
        existing: dict[str, int] = {}
        for chunk in self._chunked_keys(dimensions):
            placeholders = ",".join("?" for _ in chunk)
            existing.update(
                (str(dimension), int(value))
                for dimension, value in conn.execute(
                    "SELECT dimension, capacity "
                    "FROM resource_authority_capacity "
                    f"WHERE dimension IN ({placeholders})",
                    chunk,
                ).fetchall()
            )
        return existing

    def ensure_capacity(self, capacity: ResourceCapacity) -> None:
        """Atomically establish immutable capacity dimensions.

        Mutable inventory publication uses declare_capacity. This operation
        never overwrites an existing dimension and is therefore suitable for
        capacities that are part of an exact realized generation identity.
        """

        if type(capacity) is not ResourceCapacity:
            raise TypeError("resource authority capacity must be ResourceCapacity")
        limits = tuple(capacity.limits)
        if not limits:
            return
        dimensions = tuple(dimension for dimension, _limit in limits)

        with self._reader() as conn:
            with sqlite_read_snapshot(conn):
                existing = self._capacity_values(conn, dimensions)
        mismatch = tuple(
            (dimension, existing[dimension], limit)
            for dimension, limit in limits
            if dimension in existing and existing[dimension] != limit
        )
        if mismatch:
            raise ValueError(
                "immutable resource capacity drift: " + repr(mismatch)
            )
        if all(dimension in existing for dimension in dimensions):
            return

        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource immutable capacity ensure",
            ):
                existing = self._capacity_values(conn, dimensions)
                mismatch = tuple(
                    (dimension, existing[dimension], limit)
                    for dimension, limit in limits
                    if dimension in existing and existing[dimension] != limit
                )
                if mismatch:
                    raise ValueError(
                        "immutable resource capacity drift: " + repr(mismatch)
                    )
                missing = tuple(
                    (dimension, limit)
                    for dimension, limit in limits
                    if dimension not in existing
                )
                if not missing:
                    return

                conn.executemany(
                    "INSERT INTO resource_authority_capacity"
                    "(dimension, capacity) VALUES (?, ?)",
                    missing,
                )

                domains = tuple(
                    self._resource_event_domain("capacity:" + dimension)
                    for dimension, _limit in missing
                )
                head_generations: dict[str, int] = {}
                for chunk in self._chunked_keys(domains):
                    placeholders = ",".join("?" for _ in chunk)
                    head_generations.update(
                        (str(domain), int(generation))
                        for domain, generation in conn.execute(
                            "SELECT authority_domain, generation "
                            "FROM resource_authority_event_heads "
                            f"WHERE authority_domain IN ({placeholders})",
                            chunk,
                        ).fetchall()
                    )

                for dimension, limit in missing:
                    subject = resource_capacity_fact(
                        dimension,
                        limit,
                        modality=TruthModality.AUTHORIZED,
                    )
                    capacity_key = "capacity:" + dimension
                    domain = self._resource_event_domain(capacity_key)
                    event_generation = head_generations.get(domain, 0) + 1
                    self._append_trace_event_locked(
                        conn,
                        resource_key=capacity_key,
                        generation=event_generation,
                        subject=subject,
                        operation="capacity",
                        phase="ensured",
                        modality=TruthModality.AUTHORIZED,
                        writes=(f"capacity:{dimension}",),
                    )

    def declare_capacity(self, capacity: ResourceCapacity) -> None:
        if type(capacity) is not ResourceCapacity:
            raise TypeError("resource authority capacity must be ResourceCapacity")
        limits = tuple(capacity.limits)
        if not limits:
            return
        dimensions = tuple(dimension for dimension, _limit in limits)
        # Idempotent declarations dominate warm multi-branch startup. Prove
        # the no-op from a read snapshot first; any observed change still
        # enters the writer and is re-checked under BEGIN IMMEDIATE.
        with self._reader() as conn:
            with sqlite_read_snapshot(conn):
                existing = self._capacity_values(conn, dimensions)
        if all(existing.get(dimension) == limit for dimension, limit in limits):
            return

        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource capacity declaration",
            ):
                existing = self._capacity_values(conn, dimensions)
                changed = tuple(
                    (dimension, limit)
                    for dimension, limit in limits
                    if existing.get(dimension) != limit
                )
                if not changed:
                    return

                conn.executemany(
                    "INSERT INTO resource_authority_capacity"
                    "(dimension, capacity) VALUES (?, ?) "
                    "ON CONFLICT(dimension) DO UPDATE "
                    "SET capacity=excluded.capacity",
                    changed,
                )

                domains = tuple(
                    self._resource_event_domain("capacity:" + dimension)
                    for dimension, _limit in changed
                )
                head_generations: dict[str, int] = {}
                for chunk in self._chunked_keys(domains):
                    placeholders = ",".join("?" for _ in chunk)
                    head_generations.update(
                        (str(domain), int(generation))
                        for domain, generation in conn.execute(
                            "SELECT authority_domain, generation "
                            "FROM resource_authority_event_heads "
                            f"WHERE authority_domain IN ({placeholders})",
                            chunk,
                        ).fetchall()
                    )

                for dimension, limit in changed:
                    subject = resource_capacity_fact(
                        dimension,
                        limit,
                        modality=TruthModality.AUTHORIZED,
                    )
                    capacity_key = "capacity:" + dimension
                    domain = self._resource_event_domain(capacity_key)
                    event_generation = head_generations.get(domain, 0) + 1
                    self._append_trace_event_locked(
                        conn,
                        resource_key=capacity_key,
                        generation=event_generation,
                        subject=subject,
                        operation="capacity",
                        phase="declared",
                        modality=TruthModality.AUTHORIZED,
                        writes=(f"capacity:{dimension}",),
                    )

    @staticmethod
    def _capacity(conn) -> ResourceCapacity:
        rows = conn.execute(
            "SELECT dimension, capacity FROM resource_authority_capacity "
            "ORDER BY dimension"
        ).fetchall()
        return ResourceCapacity(tuple((str(k), int(v)) for k, v in rows))

    @staticmethod
    def _decode_claim(row) -> NoetriumUnit:
        (
            attributes,
            owner_scope,
            scope_generation,
            scope_lease_id,
            owner_lease_id,
        ) = _decode_claim_projection(row[7])
        return resource_claim(
            claim_id=str(row[0]),
            resource_key=str(row[1]),
            holder_key=str(row[2]),
            generation=int(row[3]),
            owner_scope=owner_scope,
            scope_generation=scope_generation,
            scope_lease_id=scope_lease_id,
            owner_lease_id=owner_lease_id,
            amounts=tuple(
                (str(k), int(v))
                for k, v in json.loads(str(row[4]))
            ),
            shared=tuple(str(v) for v in json.loads(str(row[5]))),
            exclusive=tuple(str(v) for v in json.loads(str(row[6]))),
            attributes=attributes,
            modality=TruthModality.AUTHORIZED,
        )

    def _decode_claim_cached(self, row) -> NoetriumUnit:
        frozen_row = tuple(row)
        claim_id = str(frozen_row[0])
        cached = self._claim_decode_cache.get(claim_id)
        if cached is not None and cached[0] == frozen_row:
            return cached[1]
        claim = self._decode_claim(frozen_row)
        self._claim_decode_cache[claim_id] = (frozen_row, claim)
        return claim

    @staticmethod
    def _claim_owner_lease_id(claim: NoetriumUnit) -> str | None:
        value = claim_field(claim, "owner_lease_id")
        return None if value is None else str(value)

    @classmethod
    def _apply_claim_delta_locked(
        cls,
        conn,
        claim: NoetriumUnit,
        *,
        add: bool,
    ) -> None:
        amounts = tuple(claim_field(claim, "amounts"))
        shared = tuple(claim_field(claim, "shared"))
        exclusive = tuple(claim_field(claim, "exclusive"))
        claim_id = str(claim_field(claim, "claim_id"))

        if add:
            if amounts:
                conn.executemany(
                    "INSERT INTO resource_authority_claim_amount_usage"
                    "(dimension, amount) VALUES (?, ?) "
                    "ON CONFLICT(dimension) DO UPDATE SET "
                    "amount=amount+excluded.amount",
                    amounts,
                )
            if shared:
                conn.executemany(
                    "INSERT INTO resource_authority_claim_shared_usage"
                    "(token, refcount) VALUES (?, 1) "
                    "ON CONFLICT(token) DO UPDATE SET refcount=refcount+1",
                    ((token,) for token in shared),
                )
            if exclusive:
                conn.executemany(
                    "INSERT INTO resource_authority_claim_exclusive_usage"
                    "(token, claim_id) VALUES (?, ?)",
                    ((token, claim_id) for token in exclusive),
                )
            return

        amount_usage: dict[str, int] = {}
        amount_dimensions = tuple(dimension for dimension, _amount in amounts)
        for chunk in cls._chunked_keys(amount_dimensions):
            placeholders = ",".join("?" for _ in chunk)
            amount_usage.update(
                (str(dimension), int(amount))
                for dimension, amount in conn.execute(
                    "SELECT dimension, amount "
                    "FROM resource_authority_claim_amount_usage "
                    f"WHERE dimension IN ({placeholders})",
                    chunk,
                ).fetchall()
            )
        for dimension, amount in amounts:
            current = amount_usage.get(dimension)
            if current is None or current < amount:
                raise RuntimeError(
                    "resource claim amount aggregate underflow: " + dimension
                )
        if amounts:
            conn.executemany(
                "UPDATE resource_authority_claim_amount_usage "
                "SET amount=amount-? WHERE dimension=?",
                ((amount, dimension) for dimension, amount in amounts),
            )
            zero_dimensions = tuple(
                dimension
                for dimension, amount in amounts
                if amount_usage[dimension] == amount
            )
            for chunk in cls._chunked_keys(zero_dimensions):
                placeholders = ",".join("?" for _ in chunk)
                conn.execute(
                    "DELETE FROM resource_authority_claim_amount_usage "
                    f"WHERE dimension IN ({placeholders}) AND amount=0",
                    chunk,
                )

        shared_usage: dict[str, int] = {}
        for chunk in cls._chunked_keys(shared):
            placeholders = ",".join("?" for _ in chunk)
            shared_usage.update(
                (str(token), int(refcount))
                for token, refcount in conn.execute(
                    "SELECT token, refcount "
                    "FROM resource_authority_claim_shared_usage "
                    f"WHERE token IN ({placeholders})",
                    chunk,
                ).fetchall()
            )
        missing_shared = next(
            (token for token in shared if shared_usage.get(token, 0) < 1),
            None,
        )
        if missing_shared is not None:
            raise RuntimeError(
                "resource claim shared aggregate underflow: " + missing_shared
            )
        if shared:
            decrement_shared = tuple(
                token for token in shared if shared_usage[token] > 1
            )
            if decrement_shared:
                conn.executemany(
                    "UPDATE resource_authority_claim_shared_usage "
                    "SET refcount=refcount-1 WHERE token=?",
                    ((token,) for token in decrement_shared),
                )
            zero_shared = tuple(
                token for token in shared if shared_usage[token] == 1
            )
            for chunk in cls._chunked_keys(zero_shared):
                placeholders = ",".join("?" for _ in chunk)
                conn.execute(
                    "DELETE FROM resource_authority_claim_shared_usage "
                    f"WHERE token IN ({placeholders}) AND refcount=1",
                    chunk,
                )

        if exclusive:
            cursor = conn.executemany(
                "DELETE FROM resource_authority_claim_exclusive_usage "
                "WHERE token=? AND claim_id=?",
                ((token, claim_id) for token in exclusive),
            )
            if cursor.rowcount != len(exclusive):
                raise RuntimeError(
                    "resource claim exclusive aggregate underflow: "
                    + ",".join(exclusive)
                )

    @staticmethod
    def _chunked_keys(values: tuple[str, ...], *, size: int = 512):
        for offset in range(0, len(values), size):
            yield values[offset : offset + size]

    @classmethod
    def _claim_usage_view_locked(
        cls,
        conn,
        claims: tuple[NoetriumUnit, ...],
        *,
        capacity_rows: dict[str, int | None] | None = None,
        amount_usage_rows: dict[str, int] | None = None,
    ) -> tuple[dict[str, int], dict[str, int], set[str], set[str]]:
        dimensions_set: set[str] = set()
        all_tokens_set: set[str] = set()
        exclusive_tokens_set: set[str] = set()
        for claim in claims:
            amounts = claim_field(claim, "amounts")
            shared = claim_field(claim, "shared")
            exclusive = claim_field(claim, "exclusive")
            dimensions_set.update(dimension for dimension, _amount in amounts)
            all_tokens_set.update(shared)
            all_tokens_set.update(exclusive)
            exclusive_tokens_set.update(exclusive)

        dimensions = tuple(dimensions_set)
        all_tokens = tuple(all_tokens_set)
        exclusive_tokens = tuple(exclusive_tokens_set)

        capacity_cache = {} if capacity_rows is None else capacity_rows
        usage_cache = {} if amount_usage_rows is None else amount_usage_rows
        missing_capacity = tuple(
            dimension for dimension in dimensions if dimension not in capacity_cache
        )
        for chunk in cls._chunked_keys(missing_capacity):
            placeholders = ",".join("?" for _ in chunk)
            found = {
                str(dimension): int(capacity)
                for dimension, capacity in conn.execute(
                    "SELECT dimension, capacity "
                    "FROM resource_authority_capacity "
                    f"WHERE dimension IN ({placeholders})",
                    chunk,
                ).fetchall()
            }
            for dimension in chunk:
                capacity_cache[dimension] = found.get(dimension)
        missing_usage = tuple(
            dimension for dimension in dimensions if dimension not in usage_cache
        )
        for chunk in cls._chunked_keys(missing_usage):
            placeholders = ",".join("?" for _ in chunk)
            found = {
                str(dimension): int(amount)
                for dimension, amount in conn.execute(
                    "SELECT dimension, amount "
                    "FROM resource_authority_claim_amount_usage "
                    f"WHERE dimension IN ({placeholders})",
                    chunk,
                ).fetchall()
            }
            for dimension in chunk:
                usage_cache[dimension] = found.get(dimension, 0)
        capacities = {
            dimension: value
            for dimension in dimensions
            if (value := capacity_cache.get(dimension)) is not None
        }
        usage = {dimension: usage_cache.get(dimension, 0) for dimension in dimensions}

        exclusive_in_use: set[str] = set()
        for chunk in cls._chunked_keys(all_tokens):
            placeholders = ",".join("?" for _ in chunk)
            exclusive_in_use.update(
                str(row[0])
                for row in conn.execute(
                    "SELECT token FROM "
                    "resource_authority_claim_exclusive_usage "
                    f"WHERE token IN ({placeholders})",
                    chunk,
                ).fetchall()
            )

        shared_in_use: set[str] = set()
        for chunk in cls._chunked_keys(exclusive_tokens):
            placeholders = ",".join("?" for _ in chunk)
            shared_in_use.update(
                str(row[0])
                for row in conn.execute(
                    "SELECT token FROM resource_authority_claim_shared_usage "
                    f"WHERE token IN ({placeholders})",
                    chunk,
                ).fetchall()
            )
        return capacities, usage, exclusive_in_use, shared_in_use

    @staticmethod
    def _validate_claim_against_usage(
        claim: NoetriumUnit,
        *,
        capacities: Mapping[str, int],
        usage: Mapping[str, int],
        exclusive_in_use: set[str],
        shared_in_use: set[str],
    ) -> None:
        for dimension, amount in claim_field(claim, "amounts"):
            if dimension not in capacities:
                raise ResourceClaimConflict(
                    f"capacity dimension is undeclared: {dimension}"
                )
            requested = usage.get(dimension, 0) + amount
            if requested > capacities[dimension]:
                raise ResourceClaimConflict(
                    f"capacity exceeded for {dimension}: "
                    f"requested={requested} limit={capacities[dimension]}"
                )

        overlap = (
            set(claim_field(claim, "shared") + claim_field(claim, "exclusive")) & exclusive_in_use
        ) | (set(claim_field(claim, "exclusive")) & shared_in_use)
        if overlap:
            raise ResourceClaimConflict(
                f"exclusive claim conflict: {tuple(sorted(overlap))}"
            )

    @classmethod
    def _validate_claim_delta_locked(
        cls,
        conn,
        claim: NoetriumUnit,
        *,
        capacity_rows: dict[str, int | None] | None = None,
        amount_usage_rows: dict[str, int] | None = None,
    ) -> None:
        capacities, usage, exclusive_in_use, shared_in_use = (
            cls._claim_usage_view_locked(
                conn,
                (claim,),
                capacity_rows=capacity_rows,
                amount_usage_rows=amount_usage_rows,
            )
        )
        cls._validate_claim_against_usage(
            claim,
            capacities=capacities,
            usage=usage,
            exclusive_in_use=exclusive_in_use,
            shared_in_use=shared_in_use,
        )

    @classmethod
    def _require_claim_parent_locked(
        cls,
        conn,
        claim: NoetriumUnit,
    ) -> None:
        """Validate a physical-ownership edge against the same Authority cut.

        A child may use zero additional capacity while borrowing its parent's
        reserved physical slot, but it must have the exact same resource
        generation and owner scope/lease. No child claim may outlive the parent.
        """
        attrs = dict(claim_field(claim, "attributes") or {})
        parent_id = attrs.get("parent_claim_id")
        if parent_id is None:
            return
        if type(parent_id) is not str or not parent_id.strip():
            raise ResourceClaimConflict("resource child requires a non-empty parent claim id")
        if parent_id == claim_field(claim, "claim_id"):
            raise ResourceClaimConflict("resource claim cannot depend on itself")
        row = conn.execute(
            "SELECT claim_id, resource_key, holder_key, generation, "
            "amounts_json, shared_json, exclusive_json, attributes_json "
            "FROM resource_authority_claims WHERE claim_id=? AND released=0",
            (parent_id,),
        ).fetchone()
        if row is None:
            raise ResourceClaimConflict("resource child has no live parent claim: " + parent_id)
        parent = cls._decode_claim(row)
        parent_key = str(claim_field(parent, "resource_key"))
        parent_generation = int(claim_field(parent, "generation"))
        # Race fence against physical retirement: a child admitted after a
        # parent's RETIRING cut would keep a valid logical claim to a world
        # that the provider is already allowed to destroy.
        retiring = conn.execute(
            "SELECT 1 FROM resource_authority_tickets "
            "WHERE resource_key=? AND generation=? "
            "AND state IN ('retiring','retired') LIMIT 1",
            (parent_key, parent_generation),
        ).fetchone()
        if retiring is not None:
            raise ResourceClaimConflict(
                "resource child cannot borrow retiring parent realization: "
                + str(parent_id)
            )
        child_key = str(claim_field(claim, "resource_key"))
        if parent_key == child_key:
            if (
                claim_field(parent, "generation") != claim_field(claim, "generation")
                or claim_field(parent, "owner_scope") != claim_field(claim, "owner_scope")
                or claim_field(parent, "scope_generation") != claim_field(claim, "scope_generation")
                or claim_field(parent, "scope_lease_id") != claim_field(claim, "scope_lease_id")
                or cls._claim_owner_lease_id(parent) != cls._claim_owner_lease_id(claim)
            ):
                raise ResourceClaimConflict(
                    "resource child crossed parent physical generation or ownership cut"
                )
            return
        # Shared physical containers may be owned by PLATFORM while each
        # dependent process has a narrower scientific Scope and a distinct
        # resource generation. An explicit cross-resource dependency freezes
        # the exact parent claim and its root scope in this writer cut.
        if (
            attrs.get("parent_resource_key") != parent_key
            or claim_field(parent, "owner_scope") != PLATFORM_SCOPE
        ):
            raise ResourceClaimConflict(
                "cross-resource child requires an exact platform-owned parent"
            )
        cls._require_generation(
            conn, parent_key, int(claim_field(parent, "generation"))
        )

    @classmethod
    def _insert_claim_locked(
        cls,
        conn,
        claim: NoetriumUnit,
        *,
        validate: bool = True,
    ) -> None:
        cls._require_claim_parent_locked(conn, claim)
        if validate:
            cls._validate_claim_delta_locked(conn, claim)
        owner_scope = claim_field(claim, "owner_scope")
        owner_lease_id = cls._claim_owner_lease_id(claim)
        conn.execute(
            "INSERT INTO resource_authority_claims"
            "(claim_id, resource_key, holder_key, generation, "
            "amounts_json, shared_json, exclusive_json, attributes_json, "
            "owner_scope_key, scope_generation, scope_lease_id, "
            "owner_lease_id, released) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (
                claim_field(claim, "claim_id"),
                claim_field(claim, "resource_key"),
                claim_field(claim, "holder_key"),
                claim_field(claim, "generation"),
                json.dumps(list(claim_field(claim, "amounts")), separators=(",", ":")),
                json.dumps(list(claim_field(claim, "shared")), separators=(",", ":")),
                json.dumps(list(claim_field(claim, "exclusive")), separators=(",", ":")),
                _encode_claim_projection(claim),
                scope_key(owner_scope),
                int(claim_field(claim, "scope_generation")),
                claim_field(claim, "scope_lease_id"),
                owner_lease_id,
            ),
        )
        cls._apply_claim_delta_locked(conn, claim, add=True)

    @staticmethod
    def _claim_release_order(
        claims: tuple[NoetriumUnit, ...],
    ) -> tuple[NoetriumUnit, ...]:
        """Order one orphan cut child-first so the parent's fence converges.

        Claims form an acyclic dependency graph: a child can be admitted only
        after its parent is live. Kahn's leaf frontier works for arbitrarily
        deep ownership in expected O(nodes + parent references) time and space,
        without recursion, sorting heaps or repeated scans. Input order is
        an already-authorized deterministic cut.
        """
        by_id = {
            str(claim_field(claim, "claim_id")): claim
            for claim in claims
        }
        child_counts = {claim_id: 0 for claim_id in by_id}
        parent_ids: dict[str, str] = {}
        for claim_id, claim in by_id.items():
            parent_id = dict(claim_field(claim, "attributes") or {}).get(
                "parent_claim_id"
            )
            if parent_id in by_id:
                parent_ids[claim_id] = parent_id
                child_counts[parent_id] += 1
        # Independent orphan claims need no sorting heap or graph traversal.
        # Preserve the caller's already-grounded deterministic order.
        if not parent_ids:
            return tuple(by_id.values())
        ready = deque(
            claim_id for claim_id, count in child_counts.items() if count == 0
        )
        ordered = []
        while ready:
            claim_id = ready.popleft()
            ordered.append(by_id[claim_id])
            parent_id = parent_ids.get(claim_id)
            if parent_id is not None:
                child_counts[parent_id] -= 1
                if child_counts[parent_id] == 0:
                    ready.append(parent_id)
        if len(ordered) != len(by_id):
            raise RuntimeError("resource claim ownership contains a cycle")
        return tuple(ordered)

    @classmethod
    def _mark_claim_released_locked(
        cls,
        conn,
        claim: NoetriumUnit,
    ) -> None:
        # Every release path (normal, scope expiry, orphan reconciliation)
        # must pass this exact Authority fence. Checking only the public
        # release_claim entry leaves an orphan-cleanup side door that can
        # retire the parent while a borrowed physical child is still live.
        claim_id = str(claim_field(claim, "claim_id"))
        child = conn.execute(
            "SELECT claim_id FROM resource_authority_claims "
            "WHERE released=0 "
            "AND json_extract(attributes_json, '$.attributes.parent_claim_id')=? "
            "LIMIT 1",
            (claim_id,),
        ).fetchone()
        if child is not None:
            raise ResourceClaimConflict(
                "cannot release resource parent claim while active child remains: "
                + claim_id
            )
        cls._apply_claim_delta_locked(conn, claim, add=False)
        cursor = conn.execute(
            "UPDATE resource_authority_claims SET released=1 "
            "WHERE claim_id=? AND released=0",
            (claim_field(claim, "claim_id"),),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(
                "resource claim release lost active authority: "
                + claim_field(claim, "claim_id")
            )

    @classmethod
    def _ensure_claim_aggregate_locked(cls, conn) -> None:
        row = conn.execute(
            "SELECT value FROM resource_authority_meta WHERE key=?",
            (_CLAIM_AGGREGATE_META_KEY,),
        ).fetchone()
        if row is not None and str(row[0]) == _CLAIM_AGGREGATE_VERSION:
            return
        active = cls._active_claims(conn)
        # One migration-time proof that historical active claims still satisfy
        # the exact algebra/capacity semantics before materializing deltas.
        compose_claims(active, capacity=cls._capacity(conn))
        conn.execute("DELETE FROM resource_authority_claim_amount_usage")
        conn.execute("DELETE FROM resource_authority_claim_shared_usage")
        conn.execute("DELETE FROM resource_authority_claim_exclusive_usage")
        for claim in active:
            cls._apply_claim_delta_locked(conn, claim, add=True)
        conn.execute(
            "INSERT INTO resource_authority_meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (_CLAIM_AGGREGATE_META_KEY, _CLAIM_AGGREGATE_VERSION),
        )

    @classmethod
    def _active_claims(
        cls,
        conn,
        resource_keys: frozenset[str] | None = None,
    ) -> tuple[NoetriumUnit, ...]:
        if resource_keys is not None and not resource_keys:
            return ()
        params: tuple[str, ...] = ()
        key_clause = ""
        if resource_keys is not None:
            params = tuple(resource_keys)
            placeholders = ",".join("?" for _ in params)
            key_clause = f" AND resource_key IN ({placeholders})"
        rows = conn.execute(
            "SELECT claim_id, resource_key, holder_key, generation, "
            "amounts_json, shared_json, exclusive_json, attributes_json "
            "FROM resource_authority_claims WHERE released=0"
            + key_clause
            + " ORDER BY claim_id",
            params,
        ).fetchall()
        return tuple(cls._decode_claim(row) for row in rows)

    def _active_claims_cached(
        self,
        conn,
        resource_keys: frozenset[str] | None = None,
    ) -> tuple[NoetriumUnit, ...]:
        if resource_keys is not None and not resource_keys:
            return ()
        params: tuple[str, ...] = ()
        key_clause = ""
        if resource_keys is not None:
            params = tuple(resource_keys)
            placeholders = ",".join("?" for _ in params)
            key_clause = f" AND resource_key IN ({placeholders})"
        rows = conn.execute(
            "SELECT claim_id, resource_key, holder_key, generation, "
            "amounts_json, shared_json, exclusive_json, attributes_json "
            "FROM resource_authority_claims WHERE released=0"
            + key_clause
            + " ORDER BY claim_id",
            params,
        ).fetchall()
        current: dict[str, tuple[tuple[object, ...], NoetriumUnit]] = {}
        claims: list[NoetriumUnit] = []
        for row in rows:
            frozen_row = tuple(row)
            claim = self._decode_claim_cached(frozen_row)
            current[str(frozen_row[0])] = (frozen_row, claim)
            claims.append(claim)
        if resource_keys is None:
            # A global live cut is a complete cache working-set proof: discard
            # identities no longer live instead of retaining historical rows.
            self._claim_decode_cache = current
        else:
            self._claim_decode_cache.update(current)
        return tuple(claims)

    def _release_orphan_claims_with_events_locked(
        self,
        conn,
        *,
        observed_at_epoch_s: float,
    ) -> tuple[NoetriumUnit, ...]:
        """Release logical orphan claims from one linearizable Authority cut.

        Scope liveness is defined exactly once by AuthoritySnapshot's recursive
        ownership projection. Physical tickets still block logical release until
        a provider proves retirement, preserving fail-close semantics.
        """
        snapshot = self._snapshot_from_reader(conn, None)
        orphaned_groups = snapshot.orphaned_claim_groups(
            now_epoch_s=observed_at_epoch_s
        )
        if not orphaned_groups:
            return ()

        released: list[NoetriumUnit] = []
        candidates = self._claim_release_order(tuple(
            claim for _lease_id, group in orphaned_groups for claim in group
        ))
        for claim in candidates:
            resource_key = str(claim_field(claim, "resource_key"))
            generation = int(claim_field(claim, "generation"))
            protected = any(
                int(ticket_field(ticket, "generation")) == generation
                and ticket_field(ticket, "state") is not TicketState.RETIRED
                for ticket in snapshot.tickets_for(resource_key)
            )
            if protected:
                continue
            try:
                self._mark_claim_released_locked(conn, claim)
            except ResourceClaimConflict:
                # A living dependent is physical truth, not orphan cleanup
                # permission. Its eventual release will unlock this parent.
                continue
            self._append_claim_event_locked(
                conn,
                claim,
                operation="release",
                phase="orphaned",
            )
            released.append(claim)
        released.sort(key=lambda row: str(claim_field(row, "claim_id")))
        return tuple(released)
    def _release_orphan_claims_for_resource_locked(
        self,
        conn,
        *,
        resource_key: str,
        observed_at_epoch_s: float,
        generation_rows: dict[str, int | None] | None = None,
        lease_rows: dict[str, NoetriumUnit | None] | None = None,
        orphan_valid_until: dict[str, float] | None = None,
        event_heads: dict[str, UnitRef | None] | None = None,
        amount_usage_rows: dict[str, int] | None = None,
    ) -> tuple[NoetriumUnit, ...]:
        """Release only dead claims that can conflict with one resource.

        Admission is a resource-local linearizable operation. It must not turn
        into global Authority maintenance. Owner liveness is re-proved from the
        canonical scope/lease chain under the same writer transaction, while
        unrelated resources remain untouched.
        """

        key = _text(resource_key, "resource key")
        if orphan_valid_until is not None:
            valid_until = orphan_valid_until.get(key)
            if valid_until is not None and observed_at_epoch_s < valid_until:
                return ()
        rows = conn.execute(
            "SELECT claim_id, resource_key, holder_key, generation, "
            "amounts_json, shared_json, exclusive_json, attributes_json, "
            "owner_scope_key, scope_generation, scope_lease_id, owner_lease_id "
            "FROM resource_authority_claims "
            "WHERE released=0 AND resource_key=? ORDER BY claim_id",
            (key,),
        ).fetchall()
        if not rows:
            if orphan_valid_until is not None:
                orphan_valid_until[key] = math.inf
            return ()

        # Owner/scope liveness is identical for claims carrying the same exact
        # persisted ownership cut.  Validate one representative per identity
        # rather than replaying the same lease/scope proof for every active
        # model-slot claim.  Dead groups are still released claim-by-claim below
        # under the canonical child-before-parent order.
        grouped: dict[
            tuple[object, object, object, object],
            list[tuple[object, ...]],
        ] = {}
        for row in rows:
            grouped.setdefault(tuple(row[8:12]), []).append(tuple(row[:8]))
        validated_scope_cuts: set[tuple[str, int, str | None]] = set()
        orphan_rows: list[tuple[object, ...]] = []
        live_valid_until = math.inf
        for owned_rows in grouped.values():
            representative = self._decode_claim(owned_rows[0])
            try:
                self._require_live_claim_owner_locked(
                    conn,
                    representative,
                    observed_at_epoch_s=observed_at_epoch_s,
                    validated_scope_cuts=validated_scope_cuts,
                    generation_rows=generation_rows,
                    lease_rows=lease_rows,
                )
            except ResourceClaimConflict:
                orphan_rows.extend(owned_rows)
            else:
                live_valid_until = min(
                    live_valid_until,
                    self._claim_owner_valid_until_at_writer_cut(
                        conn, representative, lease_rows=lease_rows
                    ),
                )

        released: list[NoetriumUnit] = []
        # Resource-local orphan cleanup must converge in one transaction
        # even when dead ownership groups cross parent/child boundaries.
        for claim in self._claim_release_order(tuple(
            self._decode_claim(row) for row in orphan_rows
        )):
            generation = int(claim_field(claim, "generation"))
            protected = conn.execute(
                "SELECT 1 FROM resource_authority_tickets "
                "WHERE resource_key=? AND generation=? "
                "AND state<>'retired' LIMIT 1",
                (key, generation),
            ).fetchone()
            if protected is not None:
                continue
            try:
                self._mark_claim_released_locked(conn, claim)
            except ResourceClaimConflict:
                continue
            self._append_claim_event_locked(
                conn,
                claim,
                operation="release",
                phase="orphaned",
                event_heads=event_heads,
            )
            if amount_usage_rows is not None:
                for dimension, _amount in claim_field(claim, "amounts"):
                    amount_usage_rows.pop(dimension, None)
            released.append(claim)
        if orphan_valid_until is not None:
            # Any dead ownership seen in this cut is conservatively rechecked
            # on the next request: a physical ticket or live child may have
            # prevented release.  The common all-live path skips safely until
            # the earliest exact lease expiry.
            orphan_valid_until[key] = (
                observed_at_epoch_s if orphan_rows else live_valid_until
            )
        return tuple(released)


    def claim_owner_live(
        self,
        claim: NoetriumUnit,
        *,
        now: float | None = None,
    ) -> bool:
        observed_at = self._lease_now(now)
        with self._reader() as conn:
            try:
                self._require_live_claim_owner_locked(
                    conn,
                    claim,
                    observed_at_epoch_s=observed_at,
                )
            except ResourceClaimConflict:
                return False
        return True

    def orphaned_claim_groups(
        self,
        *,
        now: float | None = None,
    ) -> tuple[tuple[str, tuple[NoetriumUnit, ...]], ...]:
        """Project claims whose complete Scope/lease ownership is no longer live."""
        observed_at = self._lease_now(now)
        return self.snapshot().orphaned_claim_groups(
            now_epoch_s=observed_at
        )

    def reconcile_expired_ownership(
        self,
        providers: Mapping[str, PhysicalResourceProvider],
        *,
        now: float | None = None,
    ) -> tuple[NoetriumUnit, ...]:
        """Converge expired leaf ownership to physical and logical absence.

        This is the crash/restart counterpart of ordinary topology reconcile.
        Scope/lease truth decides *whether* ownership is dead; providers only
        prove and perform the physical effect.  A leaf owner may have many
        logical claims but at most one live physical ticket.  More than one
        physical ticket is intentionally rejected because dependency order must
        then be represented by a finer ownership topology rather than guessed.
        """
        if not isinstance(providers, Mapping):
            raise TypeError("expired ownership reconciliation requires provider map")
        observed_at = self._lease_now(now)
        snapshot = self.snapshot()
        orphaned_groups = snapshot.orphaned_claim_groups(
            now_epoch_s=observed_at
        )

        released: list[NoetriumUnit] = []
        for owner_lease_id, claims in orphaned_groups:
            tickets: dict[str, NoetriumUnit] = {}
            for claim in claims:
                resource_key = str(claim_field(claim, "resource_key"))
                generation = int(claim_field(claim, "generation"))
                for ticket in snapshot.tickets_for(resource_key):
                    if (
                        int(ticket_field(ticket, "generation")) == generation
                        and ticket_field(ticket, "state") is not TicketState.RETIRED
                    ):
                        tickets[str(ticket_field(ticket, "ticket_id"))] = ticket
            if len(tickets) > 1:
                raise RuntimeError(
                    "expired owner lease spans multiple physical realizations; "
                    "ownership scope must be refined before automatic retirement: "
                    + owner_lease_id
                )
            if tickets:
                ticket = next(iter(tickets.values()))
                provider_kind = str(ticket_field(ticket, "provider_kind"))
                provider = providers.get(provider_kind)
                if provider is None:
                    raise KeyError(
                        "no physical provider for expired ownership kind: "
                        + provider_kind
                    )
                reference = self._provider_reference(ticket, snapshot)
                retiring = self.begin_retire(str(ticket_field(ticket, "ticket_id")))
                observation = provider.retire(reference, retiring)
                self.complete_retire(
                    str(ticket_field(ticket, "ticket_id")),
                    observation,
                )

            for claim in self._claim_release_order(claims):
                released.append(
                    self.release_claim(str(claim_field(claim, "claim_id")))
                )
            lease = snapshot.lease_by_id(owner_lease_id)
            if lease is not None:
                self.release_lease(lease)

        # Claims whose owner lease disappeared entirely and have no physical
        # effect are handled by the same evented orphan path.  This second pass
        # is normally empty after the groups above and keeps missing-lease
        # recovery unified with generation/TTL expiry.
        released.extend(self.reconcile_orphan_claims())
        return tuple(released)

    def _reconcile_orphan_claim_ids(
        self,
        candidate_ids: tuple[str, ...],
        *,
        observed_at_epoch_s: float,
    ) -> tuple[NoetriumUnit, ...]:
        """Re-prove and release exact orphan candidates under one writer cut."""
        if not candidate_ids:
            return ()
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource scope-owner claim reconciliation",
            ):
                released: list[NoetriumUnit] = []
                validated_scope_cuts: set[tuple[str, int, str | None]] = set()
                candidates: list[NoetriumUnit] = []
                for claim_id in candidate_ids:
                    row = conn.execute(
                        "SELECT claim_id, resource_key, holder_key, generation, "
                        "amounts_json, shared_json, exclusive_json, attributes_json, released "
                        "FROM resource_authority_claims WHERE claim_id=?",
                        (claim_id,),
                    ).fetchone()
                    if row is not None and int(row[8]) == 0:
                        candidates.append(self._decode_claim(row[:8]))
                for claim in self._claim_release_order(tuple(candidates)):
                    try:
                        self._require_live_claim_owner_locked(
                            conn,
                            claim,
                            observed_at_epoch_s=observed_at_epoch_s,
                            validated_scope_cuts=validated_scope_cuts,
                        )
                    except ResourceClaimConflict:
                        pass
                    else:
                        # Ownership recovered or was renewed between discovery
                        # and writer acquisition; fail-close and preserve it.
                        continue

                    resource_key = str(claim_field(claim, "resource_key"))
                    generation = int(claim_field(claim, "generation"))
                    protected = conn.execute(
                        "SELECT 1 FROM resource_authority_tickets "
                        "WHERE resource_key=? AND generation=? "
                        "AND state<>'retired' LIMIT 1",
                        (resource_key, generation),
                    ).fetchone()
                    if protected is not None:
                        continue
                    try:
                        self._mark_claim_released_locked(conn, claim)
                    except ResourceClaimConflict:
                        # A live child not eligible for this orphan cut still
                        # owns the parent physical capacity.
                        continue
                    self._append_claim_event_locked(
                        conn,
                        claim,
                        operation="release",
                        phase="orphaned",
                    )
                    released.append(claim)
                released.sort(key=lambda row: str(claim_field(row, "claim_id")))
                return tuple(released)

    def _orphan_claim_ids(
        self,
        *,
        observed_at_epoch_s: float,
        holder_key: str | None = None,
        resource_keys: frozenset[str] | None = None,
        claim_kinds: frozenset[str] | None = None,
    ) -> tuple[str, ...]:
        """Discover orphan claims from the smallest requested active projection."""
        projection_count = sum(
            value is not None
            for value in (holder_key, resource_keys, claim_kinds)
        )
        if projection_count > 1:
            raise ValueError(
                "orphan claim discovery accepts only one projection"
            )
        if resource_keys is not None:
            if type(resource_keys) is not frozenset or not resource_keys:
                raise ValueError(
                    "orphan resource-key projection requires non-empty frozenset"
                )
            keys = tuple(sorted(_text(key, "resource key") for key in resource_keys))
        else:
            keys = ()
        if claim_kinds is not None:
            if type(claim_kinds) is not frozenset or not claim_kinds:
                raise ValueError(
                    "orphan claim-kind projection requires non-empty frozenset"
                )
            kinds = tuple(
                sorted(_text(kind, "claim kind") for kind in claim_kinds)
            )
        else:
            kinds = ()

        with self._reader() as conn:
            with sqlite_read_snapshot(conn):
                if keys:
                    rows: list[tuple[object, ...]] = []
                    for chunk in self._chunked_keys(keys):
                        placeholders = ",".join("?" for _ in chunk)
                        rows.extend(
                            conn.execute(
                                "SELECT claim_id, resource_key, holder_key, generation, "
                                "amounts_json, shared_json, exclusive_json, attributes_json "
                                "FROM resource_authority_claims "
                                "WHERE released=0 AND resource_key IN "
                                f"({placeholders}) ORDER BY claim_id",
                                chunk,
                            ).fetchall()
                        )
                    rows.sort(key=lambda row: str(row[0]))
                elif kinds:
                    rows = []
                    for chunk in self._chunked_keys(kinds):
                        placeholders = ",".join("?" for _ in chunk)
                        rows.extend(
                            conn.execute(
                                "SELECT claim_id, resource_key, holder_key, generation, "
                                "amounts_json, shared_json, exclusive_json, attributes_json "
                                "FROM resource_authority_claims "
                                "INDEXED BY idx_resource_authority_claims_live_kind_resource "
                                "WHERE released=0 AND "
                                "json_extract(attributes_json, '$.attributes.kind') "
                                f"IN ({placeholders}) ORDER BY claim_id",
                                chunk,
                            ).fetchall()
                        )
                    rows.sort(key=lambda row: str(row[0]))
                else:
                    params: tuple[object, ...]
                    predicate: str
                    if holder_key is None:
                        predicate = "released=0"
                        params = ()
                    else:
                        predicate = "released=0 AND holder_key=?"
                        params = (_text(holder_key, "holder key"),)
                    rows = conn.execute(
                        "SELECT claim_id, resource_key, holder_key, generation, "
                        "amounts_json, shared_json, exclusive_json, attributes_json "
                        "FROM resource_authority_claims "
                        f"WHERE {predicate} ORDER BY claim_id",
                        params,
                    ).fetchall()

                candidate_ids: list[str] = []
                validated_scope_cuts: set[tuple[str, int, str | None]] = set()
                for row in rows:
                    claim = self._decode_claim_cached(row)
                    try:
                        self._require_live_claim_owner_locked(
                            conn,
                            claim,
                            observed_at_epoch_s=observed_at_epoch_s,
                            validated_scope_cuts=validated_scope_cuts,
                        )
                    except ResourceClaimConflict:
                        candidate_ids.append(
                            str(claim_field(claim, "claim_id"))
                        )
        return tuple(candidate_ids)

    def reconcile_orphan_claims_for_holder(
        self,
        holder_key: str,
    ) -> tuple[NoetriumUnit, ...]:
        """Reconcile orphan claims for one holder without a global Authority scan."""
        observed_at = self._lease_now(None)
        return self._reconcile_orphan_claim_ids(
            self._orphan_claim_ids(
                observed_at_epoch_s=observed_at,
                holder_key=holder_key,
            ),
            observed_at_epoch_s=observed_at,
        )

    def reconcile_orphan_claims_for_resource_keys(
        self,
        resource_keys: frozenset[str],
    ) -> tuple[NoetriumUnit, ...]:
        """Reconcile orphan claims only for one desired topology projection."""
        observed_at = self._lease_now(None)
        return self._reconcile_orphan_claim_ids(
            self._orphan_claim_ids(
                observed_at_epoch_s=observed_at,
                resource_keys=resource_keys,
            ),
            observed_at_epoch_s=observed_at,
        )

    def reconcile_orphan_claims_for_claim_kinds(
        self,
        claim_kinds: frozenset[str],
    ) -> tuple[NoetriumUnit, ...]:
        """Reconcile only orphan claims in one indexed semantic-kind projection."""
        observed_at = self._lease_now(None)
        return self._reconcile_orphan_claim_ids(
            self._orphan_claim_ids(
                observed_at_epoch_s=observed_at,
                claim_kinds=claim_kinds,
            ),
            observed_at_epoch_s=observed_at,
        )

    def orphaned_claim_groups_for_claim_kinds(
        self,
        claim_kinds: frozenset[str],
        *,
        now: float | None = None,
    ) -> tuple[tuple[str, tuple[NoetriumUnit, ...]], ...]:
        """Project orphan ownership only for indexed claim kinds.

        The cut includes every referenced consumer resource and complete Scope
        lease ancestry, but never decodes unrelated platform resources.
        """
        observed_at = self._lease_now(now)
        return self.snapshot_for_claim_kinds(claim_kinds).orphaned_claim_groups(
            now_epoch_s=observed_at
        )

    def reconcile_orphan_claims(self) -> tuple[NoetriumUnit, ...]:
        requested_at = self._lease_now(None)
        with self._orphan_reconcile_lock:
            # A concurrent caller that completed a recovery cut at or after
            # this caller's observation already proved every claim this caller
            # could have observed. Do not repeat the same global scan/writer
            # transaction.
            if self._orphan_reconciled_through_epoch_s >= requested_at:
                return ()
            observed_at = self._lease_now(None)
            released = self._reconcile_orphan_claim_ids(
                self._orphan_claim_ids(
                    observed_at_epoch_s=observed_at,
                ),
                observed_at_epoch_s=observed_at,
            )
            self._orphan_reconciled_through_epoch_s = observed_at
            return released

    @classmethod
    def _require_scope_generation_locked(
        cls,
        conn,
        owner_scope: NoetriumUnit,
        scope_generation: int,
        *,
        generation_rows: dict[str, int | None] | None = None,
    ) -> None:
        resource_key = _scope_resource_key(owner_scope)
        current = cls._generation_row(conn, resource_key, generation_rows)
        if current is None or current != int(scope_generation):
            raise ResourceClaimConflict(
                "scope generation is stale or missing: "
                + scope_key(owner_scope)
                + f":{scope_generation}"
            )

    def _lease_at_writer_cut(
        self,
        conn,
        lease_id: str,
        lease_rows: dict[str, NoetriumUnit | None] | None = None,
    ) -> NoetriumUnit | None:
        if lease_rows is not None and lease_id in lease_rows:
            return lease_rows[lease_id]
        row = conn.execute(
            "SELECT lease_id, resource_key, holder_key, generation, "
            "expires_at_epoch_s, acquired_at_epoch_s, metadata_json, released "
            "FROM resource_authority_leases WHERE lease_id=?",
            (lease_id,),
        ).fetchone()
        lease = None if row is None else self._decode_lease_cached(row)
        if lease_rows is not None:
            lease_rows[lease_id] = lease
        return lease

    def _claim_owner_valid_until_at_writer_cut(
        self,
        conn,
        claim: NoetriumUnit,
        *,
        lease_rows: dict[str, NoetriumUnit | None] | None = None,
    ) -> float:
        """Earliest TTL edge for an already-proved live claim owner chain."""
        expiries: list[float] = []
        scope = claim_field(claim, "owner_scope")
        scope_lease_id = claim_field(claim, "scope_lease_id")
        seen: set[str] = set()
        while scope_requires_live_lease(scope):
            if scope_lease_id is None or scope_lease_id in seen:
                raise RuntimeError("proved live scope chain lost canonical lease")
            seen.add(scope_lease_id)
            lease = self._lease_at_writer_cut(conn, scope_lease_id, lease_rows)
            if lease is None:
                raise RuntimeError("proved live scope chain lost durable lease")
            expiry = lease_field(lease, "expires_at_epoch_s")
            if expiry is not None:
                expiries.append(float(expiry))
            scope = lease_field(lease, "owner_scope")
            scope_lease_id = lease_field(lease, "scope_lease_id")

        owner_lease_id = self._claim_owner_lease_id(claim)
        if owner_lease_id is not None:
            owner_lease = self._lease_at_writer_cut(conn, owner_lease_id, lease_rows)
            if owner_lease is None:
                raise RuntimeError("proved live claim owner lost durable lease")
            expiry = lease_field(owner_lease, "expires_at_epoch_s")
            if expiry is not None:
                expiries.append(float(expiry))
        return min(expiries, default=math.inf)

    def _require_live_scope_lease_locked(
        self,
        conn,
        *,
        owner_scope: NoetriumUnit,
        scope_generation: int,
        scope_lease_id: str | None,
        observed_at_epoch_s: float,
        validated_scope_cuts: set[tuple[str, int, str | None]] | None = None,
        generation_rows: dict[str, int | None] | None = None,
        lease_rows: dict[str, NoetriumUnit | None] | None = None,
    ) -> None:
        proof_key = (scope_key(owner_scope), int(scope_generation), scope_lease_id)
        if validated_scope_cuts is not None and proof_key in validated_scope_cuts:
            return
        self._require_scope_generation_locked(
            conn, owner_scope, scope_generation, generation_rows=generation_rows
        )
        if not scope_requires_live_lease(owner_scope):
            if validated_scope_cuts is not None:
                validated_scope_cuts.add(proof_key)
            return
        if scope_lease_id is None:
            raise ResourceClaimConflict(
                "dynamic scope requires canonical live scope lease: "
                + scope_key(owner_scope)
            )
        lease = self._lease_at_writer_cut(conn, scope_lease_id, lease_rows)
        if lease is None:
            raise ResourceClaimConflict(
                "scope lease does not exist: " + scope_lease_id
            )
        if (
            lease_field(lease, "resource_key") != _scope_resource_key(owner_scope)
            or int(lease_field(lease, "generation")) != int(scope_generation)
        ):
            raise ResourceClaimConflict(
                "scope lease does not authorize requested scope generation: "
                + scope_lease_id
            )
        if not lease_live_at(
            lease,
            observed_at_epoch_s,
            current_generation=scope_generation,
        ):
            raise ResourceClaimConflict("scope lease is not live: " + scope_lease_id)
        # Scope liveness is transitive. The lease that authorizes this scope is
        # itself owned by the immediate parent scope, so validate its ownership
        # chain recursively. Static ancestors terminate the recursion.
        self._require_live_scope_lease_locked(
            conn,
            owner_scope=lease_field(lease, "owner_scope"),
            scope_generation=int(lease_field(lease, "scope_generation")),
            scope_lease_id=lease_field(lease, "scope_lease_id"),
            observed_at_epoch_s=observed_at_epoch_s,
            validated_scope_cuts=validated_scope_cuts,
            generation_rows=generation_rows,
            lease_rows=lease_rows,
        )
        if validated_scope_cuts is not None:
            validated_scope_cuts.add(proof_key)

    def _require_live_claim_owner_locked(
        self,
        conn,
        claim: NoetriumUnit,
        *,
        observed_at_epoch_s: float,
        validated_scope_cuts: set[tuple[str, int, str | None]] | None = None,
        generation_rows: dict[str, int | None] | None = None,
        lease_rows: dict[str, NoetriumUnit | None] | None = None,
    ) -> None:
        owner_scope = claim_field(claim, "owner_scope")
        scope_generation = int(claim_field(claim, "scope_generation"))
        scope_lease_id = claim_field(claim, "scope_lease_id")
        self._require_live_scope_lease_locked(
            conn,
            owner_scope=owner_scope,
            scope_generation=scope_generation,
            scope_lease_id=scope_lease_id,
            observed_at_epoch_s=observed_at_epoch_s,
            validated_scope_cuts=validated_scope_cuts,
            generation_rows=generation_rows,
            lease_rows=lease_rows,
        )

        owner_lease_id = self._claim_owner_lease_id(claim)
        if owner_lease_id is None:
            return
        owner_lease = self._lease_at_writer_cut(conn, owner_lease_id, lease_rows)
        if owner_lease is None:
            raise ResourceClaimConflict(
                "resource claim owner lease does not exist: " + owner_lease_id
            )
        if (
            lease_field(owner_lease, "owner_scope") != owner_scope
            or int(lease_field(owner_lease, "scope_generation"))
            != scope_generation
            or lease_field(owner_lease, "scope_lease_id") != scope_lease_id
        ):
            raise ResourceClaimConflict(
                "resource claim owner lease crossed scope ownership cut: "
                + owner_lease_id
            )
        self._require_live_lease_owner_locked(
            conn,
            owner_lease,
            observed_at_epoch_s=observed_at_epoch_s,
            validated_scope_cuts=validated_scope_cuts,
            generation_rows=generation_rows,
            lease_rows=lease_rows,
        )
        current_generation = self._generation_row(
            conn,
            str(lease_field(owner_lease, "resource_key")),
            generation_rows,
        )
        if (
            bool(lease_field(owner_lease, "released"))
            or current_generation is None
            or not lease_live_at(
                owner_lease,
                observed_at_epoch_s,
                current_generation=current_generation,
            )
        ):
            raise ResourceClaimConflict(
                "resource claim owner lease is not live: " + owner_lease_id
            )

    def _require_live_lease_owner_locked(
        self,
        conn,
        lease: NoetriumUnit,
        *,
        observed_at_epoch_s: float,
        validated_scope_cuts: set[tuple[str, int, str | None]] | None = None,
        generation_rows: dict[str, int | None] | None = None,
        lease_rows: dict[str, NoetriumUnit | None] | None = None,
    ) -> None:
        self._require_live_scope_lease_locked(
            conn,
            owner_scope=lease_field(lease, "owner_scope"),
            scope_generation=int(lease_field(lease, "scope_generation")),
            scope_lease_id=lease_field(lease, "scope_lease_id"),
            observed_at_epoch_s=observed_at_epoch_s,
            validated_scope_cuts=validated_scope_cuts,
            generation_rows=generation_rows,
            lease_rows=lease_rows,
        )

    def acquire_claim(self, claim: NoetriumUnit) -> NoetriumUnit:
        if not is_resource_claim(claim):
            raise TypeError("resource authority requires resource.claim Unit")
        if truth_modality(claim) is not TruthModality.DECLARED:
            raise TypeError("resource claim admission requires declared truth")
        observed_at = self._lease_now(None)
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource claim admission",
            ):
                self._release_orphan_claims_for_resource_locked(
                    conn,
                    resource_key=str(claim_field(claim, "resource_key")),
                    observed_at_epoch_s=observed_at,
                )
                self._require_generation(
                    conn,
                    claim_field(claim, "resource_key"),
                    claim_field(claim, "generation"),
                )
                self._require_live_claim_owner_locked(
                    conn,
                    claim,
                    observed_at_epoch_s=observed_at,
                )
                existing = conn.execute(
                    "SELECT claim_id, resource_key, holder_key, generation, "
                    "amounts_json, shared_json, exclusive_json, attributes_json, released "
                    "FROM resource_authority_claims WHERE claim_id=?",
                    (claim_field(claim, "claim_id"),),
                ).fetchone()
                competing = conn.execute(
                    "SELECT claim_id FROM resource_authority_claims "
                    "WHERE released=0 AND resource_key=? AND generation=? "
                    "AND claim_id<>? LIMIT 1",
                    (claim_field(claim, "resource_key"), claim_field(claim, "generation"), claim_field(claim, "claim_id")),
                ).fetchone()
                if competing is not None:
                    raise ResourceClaimConflict(
                        "resource generation already owns another active claim: "
                        f"{claim_field(claim, "resource_key")}:{claim_field(claim, "generation")}"
                    )
                if existing is not None:
                    decoded = self._decode_claim(existing[:8])
                    if (
                        int(existing[8]) == 0
                        and decoded == self._authorized_claim(claim)
                    ):
                        return decoded
                    raise ResourceClaimConflict(
                        f"claim identity already exists with different authority fact: "
                        f"{claim_field(claim, "claim_id")}"
                    )
                self._insert_claim_locked(conn, claim)
                authorized = self._authorized_claim(claim)
                self._append_claim_event_locked(
                    conn,
                    authorized,
                    operation="acquire",
                    phase="granted",
                )
                return authorized


    def admit_first(
        self,
        candidates: tuple[NoetriumUnit, ...],
    ) -> NoetriumUnit:
        """Atomically admit the first compatible candidate in caller order.

        Candidate ordering is the pure placement policy. This method owns only
        linearizable admission against the current claim set.
        """
        if type(candidates) is not tuple or not candidates:
            raise ValueError("resource admission requires non-empty claim candidates")
        if any(not is_resource_claim(row) for row in candidates):
            raise TypeError("resource admission candidates must be resource.claim Units")
        if any(
            truth_modality(row) is not TruthModality.DECLARED
            for row in candidates
        ):
            raise TypeError("resource admission candidates must be declared truth")
        logical_keys = {
            (claim_field(row, "resource_key"), claim_field(row, "generation"),
             claim_field(row, "holder_key"))
            for row in candidates
        }
        if len(logical_keys) != 1:
            raise ValueError(
                "resource admission candidates must describe one logical generation"
            )
        set_cost_scale("resource_admission_candidates", len(candidates))
        return self._admit_first_at(candidates, self._lease_now(None))

    def _admit_first_at(
        self,
        candidates: tuple[NoetriumUnit, ...],
        observed_at_epoch_s: float,
    ) -> NoetriumUnit:
        """Original single-group writer path at the caller's exact time cut."""
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource claim candidate admission",
            ):
                first = candidates[0]
                self._release_orphan_claims_for_resource_locked(
                    conn,
                    resource_key=str(claim_field(first, "resource_key")),
                    observed_at_epoch_s=observed_at_epoch_s,
                )
                self._require_generation(
                    conn,
                    claim_field(first, "resource_key"),
                    claim_field(first, "generation"),
                )
                validated_scope_cuts: set[tuple[str, int, str | None]] = set()
                for candidate in candidates:
                    self._require_live_claim_owner_locked(
                        conn,
                        candidate,
                        observed_at_epoch_s=observed_at_epoch_s,
                        validated_scope_cuts=validated_scope_cuts,
                    )
                existing_rows = conn.execute(
                    "SELECT claim_id, resource_key, holder_key, generation, amounts_json, "
                    "shared_json, exclusive_json, attributes_json FROM resource_authority_claims "
                    "WHERE released=0 AND resource_key=? AND generation=? AND holder_key=? "
                    "ORDER BY claim_id",
                    (claim_field(first, "resource_key"), claim_field(first, "generation"),
                     claim_field(first, "holder_key")),
                ).fetchall()
                if existing_rows:
                    existing = tuple(self._decode_claim(row) for row in existing_rows)
                    existing_by_digest = {
                        row.semantic_digest: row
                        for row in existing
                    }
                    for candidate in candidates:
                        authorized_candidate = self._authorized_claim(candidate)
                        matched = existing_by_digest.get(
                            authorized_candidate.semantic_digest
                        )
                        if matched is not None:
                            return matched
                    raise ResourceClaimConflict(
                        "logical resource generation already owns a different claim"
                    )

                (
                    capacities,
                    usage,
                    exclusive_in_use,
                    shared_in_use,
                ) = self._claim_usage_view_locked(conn, candidates)
                last_error: ResourceClaimConflict | None = None
                for claim in candidates:
                    add_cost_work("resource_admission_candidates_examined", 1)
                    try:
                        self._validate_claim_against_usage(
                            claim,
                            capacities=capacities,
                            usage=usage,
                            exclusive_in_use=exclusive_in_use,
                            shared_in_use=shared_in_use,
                        )
                    except ResourceClaimConflict as exc:
                        last_error = exc
                        continue
                    self._insert_claim_locked(
                        conn,
                        claim,
                        validate=False,
                    )
                    authorized = self._authorized_claim(claim)
                    self._append_claim_event_locked(
                        conn,
                        authorized,
                        operation="acquire",
                        phase="granted",
                    )
                    return authorized
                raise ResourceClaimConflict(
                    "no resource claim candidate is compatible with current authority state"
                ) from last_error

    def admit_bundle(
        self,
        candidate_groups: tuple[tuple[NoetriumUnit, ...], ...],
    ) -> tuple[NoetriumUnit, ...]:
        """Atomically admit one compatible claim from every logical group.

        Candidate policy remains caller-owned.  Naturally concurrent callers
        may share one physical durable commit, but every operation retains its
        own atomic SAVEPOINT and waits for that outer commit before returning.
        """
        if type(candidate_groups) is not tuple or not candidate_groups:
            raise ValueError("resource bundle admission requires non-empty candidate groups")
        logical_keys: list[tuple[object, object, object]] = []
        candidate_count = 0
        for candidates in candidate_groups:
            if type(candidates) is not tuple or not candidates:
                raise ValueError("resource bundle candidate group must be non-empty")
            if any(not is_resource_claim(row) for row in candidates):
                raise TypeError("resource bundle candidates must be resource.claim Units")
            if any(
                truth_modality(row) is not TruthModality.DECLARED
                for row in candidates
            ):
                raise TypeError("resource bundle candidates must be declared truth")
            group_keys = {
                (
                    claim_field(row, "resource_key"),
                    claim_field(row, "generation"),
                    claim_field(row, "holder_key"),
                )
                for row in candidates
            }
            if len(group_keys) != 1:
                raise ValueError(
                    "resource bundle candidate group must describe one logical generation"
                )
            logical_keys.append(next(iter(group_keys)))
            candidate_count += len(candidates)
        if len(set(logical_keys)) != len(logical_keys):
            raise ValueError("resource bundle contains duplicate logical generations")

        set_cost_scale("resource_admission_bundle_groups", len(candidate_groups))
        set_cost_scale("resource_admission_candidates", candidate_count)
        observed_at = self._lease_now(None)
        result = self._submit_claim_mutation(
            "admit_bundle",
            candidate_groups,
            observed_at_epoch_s=observed_at,
        )
        if not isinstance(result, tuple):
            raise RuntimeError("resource bundle admission lost typed result")
        return result

    def _admit_bundle_locked(
        self,
        conn,
        candidate_groups: object,
        *,
        observed_at_epoch_s: float,
        pending: _PendingClaimMutation,
        generation_rows: dict[str, int | None],
        lease_rows: dict[str, NoetriumUnit | None],
        orphan_valid_until: dict[str, float],
        event_heads: dict[str, UnitRef | None],
        capacity_rows: dict[str, int | None],
        amount_usage_rows: dict[str, int],
    ) -> tuple[NoetriumUnit, ...]:
        if type(candidate_groups) is not tuple:
            raise TypeError("grouped resource bundle payload must be tuple")
        local_orphan_valid_until = dict(orphan_valid_until)
        local_amount_usage_rows = dict(amount_usage_rows)
        local_event_heads = dict(event_heads)
        validated_scope_cuts: set[tuple[str, int, str | None]] = set()
        selected: list[NoetriumUnit] = []
        for candidates in candidate_groups:
            first = candidates[0]
            resource_key = str(claim_field(first, "resource_key"))
            generation = int(claim_field(first, "generation"))
            holder_key = str(claim_field(first, "holder_key"))
            self._release_orphan_claims_for_resource_locked(
                conn,
                resource_key=resource_key,
                observed_at_epoch_s=observed_at_epoch_s,
                generation_rows=generation_rows,
                lease_rows=lease_rows,
                orphan_valid_until=local_orphan_valid_until,
                event_heads=local_event_heads,
                amount_usage_rows=local_amount_usage_rows,
            )
            self._require_generation(
                conn, resource_key, generation, generation_rows=generation_rows
            )
            for candidate in candidates:
                self._require_live_claim_owner_locked(
                    conn,
                    candidate,
                    observed_at_epoch_s=observed_at_epoch_s,
                    validated_scope_cuts=validated_scope_cuts,
                    generation_rows=generation_rows,
                    lease_rows=lease_rows,
                )

            existing_rows = conn.execute(
                "SELECT claim_id, resource_key, holder_key, generation, "
                "amounts_json, shared_json, exclusive_json, attributes_json "
                "FROM resource_authority_claims WHERE released=0 "
                "AND resource_key=? AND generation=? AND holder_key=? "
                "ORDER BY claim_id",
                (resource_key, generation, holder_key),
            ).fetchall()
            if existing_rows:
                existing = tuple(self._decode_claim(row) for row in existing_rows)
                existing_by_digest = {
                    row.semantic_digest: row for row in existing
                }
                matched = next(
                    (
                        existing_by_digest.get(
                            self._authorized_claim(candidate).semantic_digest
                        )
                        for candidate in candidates
                        if self._authorized_claim(candidate).semantic_digest
                        in existing_by_digest
                    ),
                    None,
                )
                if matched is None:
                    raise ResourceClaimConflict(
                        "logical resource generation already owns a different claim"
                    )
                selected.append(matched)
                continue

            last_error: ResourceClaimConflict | None = None
            chosen: NoetriumUnit | None = None
            for candidate in candidates:
                pending.examined_candidates += 1
                try:
                    # Aggregate tables include claims inserted earlier in the
                    # same outer transaction, including successful operations
                    # earlier in this linearized group-commit cut.
                    self._validate_claim_delta_locked(
                        conn,
                        candidate,
                        capacity_rows=capacity_rows,
                        amount_usage_rows=local_amount_usage_rows,
                    )
                except ResourceClaimConflict as exc:
                    last_error = exc
                    continue
                self._insert_claim_locked(conn, candidate, validate=False)
                for dimension, amount in claim_field(candidate, "amounts"):
                    if dimension in local_amount_usage_rows:
                        local_amount_usage_rows[dimension] += int(amount)
                chosen = self._authorized_claim(candidate)
                self._append_claim_event_locked(
                    conn,
                    chosen,
                    operation="acquire",
                    phase="granted",
                    event_heads=local_event_heads,
                )
                break
            if chosen is None:
                raise ResourceClaimConflict(
                    "no complete resource claim bundle is compatible with current authority state"
                ) from last_error
            selected.append(chosen)
            local_orphan_valid_until[resource_key] = min(
                local_orphan_valid_until.get(resource_key, math.inf),
                self._claim_owner_valid_until_at_writer_cut(
                    conn, chosen, lease_rows=lease_rows
                ),
            )
        orphan_valid_until.clear()
        orphan_valid_until.update(local_orphan_valid_until)
        amount_usage_rows.clear()
        amount_usage_rows.update(local_amount_usage_rows)
        event_heads.clear()
        event_heads.update(local_event_heads)
        return tuple(selected)

    def release_claim(self, claim_id: str) -> NoetriumUnit:
        key = _text(claim_id, "claim id")
        result = self._submit_claim_mutation("release_claim", key)
        if not is_resource_claim(result):
            raise RuntimeError("resource claim release lost typed result")
        return result

    def _release_claim_locked(
        self,
        conn,
        key: str,
        *,
        event_heads: dict[str, UnitRef | None] | None = None,
        amount_usage_rows: dict[str, int] | None = None,
    ) -> NoetriumUnit:
        row = conn.execute(
            "SELECT claim_id, resource_key, holder_key, generation, "
            "amounts_json, shared_json, exclusive_json, attributes_json, released "
            "FROM resource_authority_claims WHERE claim_id=?",
            (key,),
        ).fetchone()
        if row is None:
            raise KeyError(key)
        claim = self._decode_claim(row[:8])
        if int(row[8]) == 1:
            return claim
        physical = conn.execute(
            "SELECT 1 FROM resource_authority_tickets "
            "WHERE resource_key=? AND generation=? "
            "AND state IN ('prepared','bound','retiring') LIMIT 1",
            (claim_field(claim, "resource_key"), claim_field(claim, "generation")),
        ).fetchone()
        if physical is not None:
            raise RuntimeError(
                "cannot release resource claim before physical realization "
                f"is confirmed retired: {claim_field(claim, 'resource_key')}"
            )
        self._mark_claim_released_locked(conn, claim)
        self._append_claim_event_locked(
            conn,
            claim,
            operation="release",
            phase="committed",
            event_heads=event_heads,
        )
        if amount_usage_rows is not None:
            for dimension, _amount in claim_field(claim, "amounts"):
                amount_usage_rows.pop(dimension, None)
        return claim

    def acquire_lease(self, lease: NoetriumUnit) -> NoetriumUnit:
        if not is_authority_lease(lease):
            raise TypeError("resource authority requires resource.lease Unit")
        if truth_modality(lease) is not TruthModality.DECLARED:
            raise TypeError("resource lease admission requires declared truth")
        if lease_field(lease, "released"):
            raise ValueError("cannot acquire a released lease")
        observed_at = self._lease_now(None)
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource lease acquire",
            ):
                self._require_generation(
                    conn,
                    lease_field(lease, "resource_key"),
                    lease_field(lease, "generation"),
                )
                self._require_live_lease_owner_locked(
                    conn,
                    lease,
                    observed_at_epoch_s=observed_at,
                )
                admission_token = "lease-admission:" + lease_field(lease, "resource_key")
                current_claim_rows = conn.execute(
                    "SELECT claim_id, resource_key, holder_key, generation, "
                    "amounts_json, shared_json, exclusive_json, attributes_json "
                    "FROM resource_authority_claims WHERE released=0 "
                    "AND resource_key=? AND generation=?",
                    (lease_field(lease, "resource_key"), lease_field(lease, "generation")),
                ).fetchall()
                if any(
                    admission_token in tuple(claim_field(self._decode_claim(claim_row), "exclusive"))
                    for claim_row in current_claim_rows
                ):
                    raise RuntimeError(
                        "resource lease admission is fenced for retirement: "
                        + lease_field(lease, "resource_key")
                    )
                row = conn.execute(
                    "SELECT lease_id, resource_key, holder_key, generation, "
                    "expires_at_epoch_s, acquired_at_epoch_s, metadata_json, released "
                    "FROM resource_authority_leases WHERE lease_id=?",
                    (lease_field(lease, "lease_id"),),
                ).fetchone()
                if row is not None:
                    existing = self._decode_lease(row)
                    if (
                        not lease_field(existing, "released")
                        and lease_field(existing, "resource_key") == lease_field(lease, "resource_key")
                        and lease_field(existing, "holder_key") == lease_field(lease, "holder_key")
                        and lease_field(existing, "generation") == lease_field(lease, "generation")
                        and lease_field(existing, "owner_scope") == lease_field(lease, "owner_scope")
                        and lease_field(existing, "scope_generation") == lease_field(lease, "scope_generation")
                        and lease_field(existing, "scope_lease_id") == lease_field(lease, "scope_lease_id")
                        and dict(lease_field(existing, "metadata") or {}) == dict(lease_field(lease, "metadata") or {})
                    ):
                        return existing
                    raise RuntimeError(
                        "lease identity already exists with different "
                        f"generation/fact: {lease_field(lease, "lease_id")}"
                    )
                conn.execute(
                    "INSERT INTO resource_authority_leases"
                    "(lease_id, resource_key, holder_key, generation, "
                    "expires_at_epoch_s, acquired_at_epoch_s, "
                    "owner_scope_key, scope_generation, scope_lease_id, "
                    "metadata_json, released) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                    (
                        lease_field(lease, "lease_id"),
                        lease_field(lease, "resource_key"),
                        lease_field(lease, "holder_key"),
                        lease_field(lease, "generation"),
                        lease_field(lease, "expires_at_epoch_s"),
                        lease_field(lease, "acquired_at_epoch_s"),
                        scope_key(lease_field(lease, "owner_scope")),
                        int(lease_field(lease, "scope_generation")),
                        lease_field(lease, "scope_lease_id"),
                        _encode_lease_projection(lease),
                    ),
                )
                authorized = self._authorized_lease(lease)
                self._append_lease_event_locked(
                    conn,
                    authorized,
                    operation="acquire",
                    phase="granted",
                )
                return authorized

    @staticmethod
    def _require_exact_lease_generation(
        observed: NoetriumUnit,
        expected: NoetriumUnit,
    ) -> None:
        if not is_authority_lease(expected):
            raise TypeError("lease mutation requires resource.lease Unit")
        if (
            lease_field(observed, "lease_id") != lease_field(expected, "lease_id")
            or lease_field(observed, "resource_key") != lease_field(expected, "resource_key")
            or lease_field(observed, "holder_key") != lease_field(expected, "holder_key")
            or lease_field(observed, "generation") != lease_field(expected, "generation")
            or lease_field(observed, "owner_scope") != lease_field(expected, "owner_scope")
            or lease_field(observed, "scope_generation") != lease_field(expected, "scope_generation")
            or lease_field(observed, "scope_lease_id") != lease_field(expected, "scope_lease_id")
            or dict(lease_field(observed, "metadata") or {}) != dict(lease_field(expected, "metadata") or {})
        ):
            raise RuntimeError(
                "resource lease mutation is fenced by a different generation"
            )

    def release_lease(self, lease: NoetriumUnit) -> NoetriumUnit:
        if not is_authority_lease(lease):
            raise TypeError("lease release requires resource.lease Unit")
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource lease release",
            ):
                row = conn.execute(
                    "SELECT lease_id, resource_key, holder_key, generation, "
                    "expires_at_epoch_s, acquired_at_epoch_s, metadata_json, released "
                    "FROM resource_authority_leases WHERE lease_id=?",
                    (lease_field(lease, "lease_id"),),
                ).fetchone()
                if row is None:
                    raise KeyError(lease_field(lease, "lease_id"))
                current = self._decode_lease(row)
                self._require_exact_lease_generation(current, lease)
                if lease_field(current, "released"):
                    return current
                conn.execute(
                    "UPDATE resource_authority_leases SET released=1 "
                    "WHERE lease_id=? AND generation=?",
                    (lease_field(lease, "lease_id"), lease_field(lease, "generation")),
                )
                released = self._authorized_lease(current, released=True)
                self._append_lease_event_locked(
                    conn,
                    released,
                    operation="release",
                    phase="committed",
                )
                return released

    _LEASE_CLOCK_ANCHOR_KEY = "lease-clock-anchor-v1"

    @staticmethod
    def _clock_anchor_payload(
        reading: LeaseClockReading,
        logical_epoch_seconds: float,
    ) -> dict[str, object]:
        return {
            "host_identity_digest": reading.host_identity_digest,
            "boot_identity_digest": reading.boot_identity_digest,
            "elapsed_seconds": reading.elapsed_seconds,
            "logical_epoch_seconds": logical_epoch_seconds,
        }

    def _resolve_clock_domain(
        self,
        conn,
        reading: LeaseClockReading,
    ) -> tuple[str, str, float, float]:
        if not isinstance(reading, LeaseClockReading):
            raise TypeError("resource authority lease clock returned invalid reading")
        row = conn.execute(
            "SELECT value FROM resource_authority_meta WHERE key=?",
            (self._LEASE_CLOCK_ANCHOR_KEY,),
        ).fetchone()
        if row is None:
            logical_epoch = float(reading.wall_epoch_seconds)
            if not math.isfinite(logical_epoch) or logical_epoch <= 0:
                raise RuntimeError(
                    "resource authority lease clock has invalid initial wall epoch"
                )
            payload = self._clock_anchor_payload(reading, logical_epoch)
            conn.execute(
                "INSERT INTO resource_authority_meta(key,value) VALUES(?,?)",
                (
                    self._LEASE_CLOCK_ANCHOR_KEY,
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                ),
            )
            return (
                reading.host_identity_digest,
                reading.boot_identity_digest,
                reading.elapsed_seconds,
                logical_epoch,
            )
        host, boot, anchor_elapsed, anchor_epoch = (
            self._decode_clock_anchor_value(row[0])
        )
        if host != reading.host_identity_digest:
            raise RuntimeError(
                "resource authority belongs to a different host clock domain"
            )
        if boot != reading.boot_identity_digest:
            # Host reboot is a universal fencing event. Advancing every known
            # resource generation makes all pre-reboot leases, claims and
            # physical bindings stale without pretending physical absence.
            conn.execute(
                "UPDATE resource_authority_generations "
                "SET generation=generation+1"
            )
            conn.execute("DELETE FROM resource_authority_single_flights")
            for resource_key, generation in conn.execute(
                "SELECT resource_key, generation "
                "FROM resource_authority_generations ORDER BY resource_key"
            ).fetchall():
                key = str(resource_key)
                current_generation = int(generation)
                self._append_trace_event_locked(
                    conn,
                    resource_key=key,
                    generation=current_generation,
                    subject=self._resource_event_subject(key, current_generation),
                    operation="fence",
                    phase="reboot",
                    modality=TruthModality.AUTHORIZED,
                    reads=(f"resource:{key}:generation",),
                    writes=(f"resource:{key}:generation",),
                )
            logical_epoch = float(reading.wall_epoch_seconds)
            if not math.isfinite(logical_epoch) or logical_epoch <= 0:
                raise RuntimeError(
                    "resource authority lease clock has invalid reboot wall epoch"
                )
            replacement = self._clock_anchor_payload(reading, logical_epoch)
            conn.execute(
                "UPDATE resource_authority_meta SET value=? WHERE key=?",
                (
                    json.dumps(
                        replacement,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    self._LEASE_CLOCK_ANCHOR_KEY,
                ),
            )
            return (
                reading.host_identity_digest,
                reading.boot_identity_digest,
                reading.elapsed_seconds,
                logical_epoch,
            )
        if reading.elapsed_seconds < anchor_elapsed:
            raise RuntimeError(
                "same-boot suspend-aware lease clock moved backwards"
            )
        return (host, boot, anchor_elapsed, anchor_epoch)

    def _refresh_clock_domain(
        self,
        reading: LeaseClockReading,
    ) -> tuple[str, str, float, float]:
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource authority lease clock fence",
            ):
                domain = self._resolve_clock_domain(conn, reading)
        self._clock_domain = domain
        return domain

    def _lease_now(self, now: float | None) -> float:
        # `now` remains accepted by higher-level recovery protocols only as an
        # input-validation surface. Caller wall time never decides lease liveness.
        if now is not None:
            value = float(now)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(
                    "resource lease observation time must be finite and positive"
                )
        reading = self._clock.read()
        domain = self._clock_domain
        if domain is None:
            domain = self._refresh_clock_domain(reading)
        host, boot, anchor_elapsed, anchor_epoch = domain
        if (
            reading.host_identity_digest != host
            or reading.boot_identity_digest != boot
            or reading.elapsed_seconds < anchor_elapsed
        ):
            domain = self._refresh_clock_domain(reading)
            host, boot, anchor_elapsed, anchor_epoch = domain
        return anchor_epoch + (reading.elapsed_seconds - anchor_elapsed)

    @staticmethod
    def _decode_lease(row) -> NoetriumUnit:
        metadata, owner_scope, scope_generation, scope_lease_id = (
            _decode_lease_projection(row[6])
        )
        return authority_lease(
            lease_id=str(row[0]),
            resource_key=str(row[1]),
            holder_key=str(row[2]),
            generation=int(row[3]),
            owner_scope=owner_scope,
            scope_generation=scope_generation,
            scope_lease_id=scope_lease_id,
            expires_at_epoch_s=None if row[4] is None else float(row[4]),
            released=bool(row[7]),
            acquired_at_epoch_s=None if row[5] is None else float(row[5]),
            metadata=metadata,
            modality=TruthModality.AUTHORIZED,
        )

    def _decode_lease_cached(self, row) -> NoetriumUnit:
        frozen_row = tuple(row)
        lease_id = str(frozen_row[0])
        cached = self._lease_decode_cache.get(lease_id)
        if cached is not None and cached[0] == frozen_row:
            return cached[1]
        lease = self._decode_lease(frozen_row)
        self._lease_decode_cache[lease_id] = (frozen_row, lease)
        return lease

    def get_lease(self, lease_id: str) -> NoetriumUnit:
        key = _text(lease_id, "lease id")
        with self._reader() as conn:
            row = conn.execute(
                "SELECT lease_id, resource_key, holder_key, generation, "
                "expires_at_epoch_s, acquired_at_epoch_s, metadata_json, released "
                "FROM resource_authority_leases "
                "WHERE lease_id=?",
                (key,),
            ).fetchone()
        if row is None:
            raise KeyError(key)
        return self._decode_lease(row)

    def acquire_consumer_lease(
        self,
        *,
        lease_id: str,
        resource_key: str,
        holder_key: str,
        owner_scope: NoetriumUnit,
        scope_lease: NoetriumUnit | None = None,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> NoetriumUnit:
        """Acquire an explicit-release resource lease owned by one Scope.

        Scope ownership is mandatory. Dynamic scopes are authorized only by
        their canonical live scope lease; static scopes carry no scope lease.
        """
        generation = self.ensure_generation(resource_key)
        scope_generation, scope_lease_id = self.scope_ownership_cut(
            owner_scope,
            scope_lease=scope_lease,
        )
        return self.acquire_lease(
            authority_lease(
                lease_id=_text(lease_id, "lease id"),
                resource_key=generation.resource_key,
                holder_key=_text(holder_key, "lease holder"),
                generation=generation.generation,
                owner_scope=owner_scope,
                scope_generation=scope_generation.generation,
                scope_lease_id=scope_lease_id,
                metadata=metadata,
            )
        )

    def acquire_ttl_lease(
        self,
        *,
        lease_id: str,
        resource_key: str,
        holder_key: str,
        owner_scope: NoetriumUnit,
        scope_lease: NoetriumUnit | None = None,
        ttl_seconds: float,
        now: float | None = None,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> NoetriumUnit:
        ttl = float(ttl_seconds)
        if not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("resource lease ttl_seconds must be finite and positive")
        observed_at = self._lease_now(now)
        generation = self.ensure_generation(resource_key)
        scope_generation, scope_lease_id = self.scope_ownership_cut(
            owner_scope,
            scope_lease=scope_lease,
        )
        return self.acquire_lease(
            authority_lease(
                lease_id=_text(lease_id, "lease id"),
                resource_key=generation.resource_key,
                holder_key=_text(holder_key, "lease holder"),
                generation=generation.generation,
                owner_scope=owner_scope,
                scope_generation=scope_generation.generation,
                scope_lease_id=scope_lease_id,
                expires_at_epoch_s=observed_at + ttl,
                acquired_at_epoch_s=observed_at,
                metadata=metadata,
            )
        )

    def acquire_exclusive_ttl_lease(
        self,
        *,
        lease_id: str,
        resource_key: str,
        holder_key: str,
        owner_scope: NoetriumUnit,
        scope_lease: NoetriumUnit | None = None,
        ttl_seconds: float,
        now: float | None = None,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> NoetriumUnit:
        """Atomically acquire the sole live lease for one resource generation."""
        lease_key = _text(lease_id, "lease id")
        resource = _text(resource_key, "resource key")
        holder = _text(holder_key, "lease holder")
        ttl = float(ttl_seconds)
        if not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("resource lease ttl_seconds must be finite and positive")
        observed_at = self._lease_now(now)
        requested_metadata = {} if metadata is None else dict(metadata)
        generation = self.ensure_generation(resource)
        scope_generation, scope_lease_id = self.scope_ownership_cut(
            owner_scope,
            scope_lease=scope_lease,
        )
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="exclusive resource lease acquire",
            ):
                self._require_generation(conn, resource, generation.generation)
                self._require_live_scope_lease_locked(
                    conn,
                    owner_scope=owner_scope,
                    scope_generation=scope_generation.generation,
                    scope_lease_id=scope_lease_id,
                    observed_at_epoch_s=observed_at,
                )
                admission_token = "lease-admission:" + resource
                claim_rows = conn.execute(
                    "SELECT claim_id, resource_key, holder_key, generation, "
                    "amounts_json, shared_json, exclusive_json, attributes_json "
                    "FROM resource_authority_claims WHERE released=0 "
                    "AND resource_key=? AND generation=?",
                    (resource, generation.generation),
                ).fetchall()
                if any(
                    admission_token in tuple(claim_field(self._decode_claim(row), "exclusive"))
                    for row in claim_rows
                ):
                    raise RuntimeError(
                        "resource lease admission is fenced for retirement: "
                        + resource
                    )
                rows = conn.execute(
                    "SELECT lease_id, resource_key, holder_key, generation, "
                    "expires_at_epoch_s, acquired_at_epoch_s, metadata_json, released "
                    "FROM resource_authority_leases WHERE resource_key=? "
                    "AND generation=? AND released=0 ORDER BY lease_id",
                    (resource, generation.generation),
                ).fetchall()
                live = tuple(
                    lease
                    for lease in (self._decode_lease(row) for row in rows)
                    if lease_live_at(
                        lease,
                        observed_at,
                        current_generation=generation.generation,
                    )
                )
                if live:
                    if len(live) != 1:
                        raise RuntimeError(
                            "exclusive resource contains multiple live leases"
                        )
                    current = live[0]
                    if (
                        lease_field(current, "lease_id") != lease_key
                        or lease_field(current, "holder_key") != holder
                        or lease_field(current, "owner_scope") != owner_scope
                        or int(lease_field(current, "scope_generation"))
                        != scope_generation.generation
                        or lease_field(current, "scope_lease_id") != scope_lease_id
                        or dict(lease_field(current, "metadata") or {})
                        != requested_metadata
                    ):
                        raise RuntimeError(
                            "exclusive resource lease is held by another owner"
                        )
                    expires = observed_at + ttl
                    conn.execute(
                        "UPDATE resource_authority_leases SET expires_at_epoch_s=? "
                        "WHERE lease_id=?",
                        (expires, lease_key),
                    )
                    renewed = self._authorized_lease(
                        current, expires_at_epoch_s=expires
                    )
                    self._append_lease_event_locked(
                        conn, renewed, operation="renew", phase="committed"
                    )
                    return renewed
                expires = observed_at + ttl
                existing = conn.execute(
                    "SELECT 1 FROM resource_authority_leases WHERE lease_id=?",
                    (lease_key,),
                ).fetchone()
                projection = _encode_lease_projection(
                    authority_lease(
                        lease_id=lease_key,
                        resource_key=resource,
                        holder_key=holder,
                        generation=generation.generation,
                        owner_scope=owner_scope,
                        scope_generation=scope_generation.generation,
                        scope_lease_id=scope_lease_id,
                        expires_at_epoch_s=expires,
                        acquired_at_epoch_s=observed_at,
                        metadata=requested_metadata,
                    )
                )
                if existing is None:
                    conn.execute(
                        "INSERT INTO resource_authority_leases"
                        "(lease_id, resource_key, holder_key, generation, "
                        "expires_at_epoch_s, acquired_at_epoch_s, metadata_json, released) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                        (
                            lease_key, resource, holder, generation.generation,
                            expires, observed_at, projection,
                        ),
                    )
                else:
                    conn.execute(
                        "UPDATE resource_authority_leases SET resource_key=?, holder_key=?, "
                        "generation=?, expires_at_epoch_s=?, acquired_at_epoch_s=?, "
                        "metadata_json=?, released=0 WHERE lease_id=?",
                        (
                            resource, holder, generation.generation, expires,
                            observed_at, projection, lease_key,
                        ),
                    )
                granted = authority_lease(
                    lease_id=lease_key,
                    resource_key=resource,
                    holder_key=holder,
                    generation=generation.generation,
                    owner_scope=owner_scope,
                    scope_generation=scope_generation.generation,
                    scope_lease_id=scope_lease_id,
                    expires_at_epoch_s=expires,
                    released=False,
                    acquired_at_epoch_s=observed_at,
                    metadata=requested_metadata,
                    modality=TruthModality.AUTHORIZED,
                )
                self._append_lease_event_locked(
                    conn, granted, operation="acquire", phase="granted"
                )
                return granted

    def renew_lease(
        self,
        lease: NoetriumUnit,
        *,
        ttl_seconds: float,
        now: float | None = None,
    ) -> NoetriumUnit:
        if not is_authority_lease(lease):
            raise TypeError("lease renewal requires resource.lease Unit")
        ttl = float(ttl_seconds)
        if not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("resource lease ttl_seconds must be finite and positive")
        observed_at = self._lease_now(now)
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource lease renew",
            ):
                row = conn.execute(
                    "SELECT lease_id, resource_key, holder_key, generation, "
                    "expires_at_epoch_s, acquired_at_epoch_s, metadata_json, released "
                    "FROM resource_authority_leases WHERE lease_id=?",
                    (lease_field(lease, "lease_id"),),
                ).fetchone()
                if row is None:
                    raise KeyError(lease_field(lease, "lease_id"))
                current = self._decode_lease(row)
                self._require_exact_lease_generation(current, lease)
                self._require_generation(
                    conn, lease_field(current, "resource_key"), lease_field(current, "generation")
                )
                self._require_live_lease_owner_locked(
                    conn,
                    current,
                    observed_at_epoch_s=observed_at,
                )
                if lease_field(current, "released"):
                    raise RuntimeError(
                        f"cannot renew released resource lease: {lease_field(current, "lease_id")}"
                    )
                if (
                    lease_field(current, "expires_at_epoch_s") is not None
                    and lease_field(current, "expires_at_epoch_s") <= observed_at
                ):
                    raise RuntimeError(
                        f"cannot renew expired resource lease: {lease_field(current, "lease_id")}"
                    )
                expires = observed_at + ttl
                conn.execute(
                    "UPDATE resource_authority_leases SET expires_at_epoch_s=? "
                    "WHERE lease_id=? AND generation=?",
                    (expires, lease_field(current, "lease_id"), lease_field(current, "generation")),
                )
                renewed = self._authorized_lease(
                    current,
                    expires_at_epoch_s=expires,
                )
                self._append_lease_event_locked(
                    conn,
                    renewed,
                    operation="renew",
                    phase="committed",
                )
                return renewed

    def renew_leases(
        self,
        leases: tuple[NoetriumUnit, ...],
        *,
        ttl_seconds: float,
        now: float | None = None,
    ) -> tuple[NoetriumUnit, ...]:
        if type(leases) is not tuple or any(
            not is_authority_lease(row) for row in leases
        ):
            raise TypeError(
                "resource lease batch renewal requires tuple[NoetriumUnit, ...]"
            )
        ids = tuple(str(lease_field(row, "lease_id")) for row in leases)
        if len(set(ids)) != len(ids):
            raise ValueError("resource lease batch renewal requires unique ids")
        if not leases:
            return ()
        ttl = float(ttl_seconds)
        if not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("resource lease ttl_seconds must be finite and positive")
        observed_at = self._lease_now(now)
        expires = observed_at + ttl
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource lease batch renew",
            ):
                placeholders = ",".join("?" for _ in ids)
                fetched = conn.execute(
                    "SELECT lease_id, resource_key, holder_key, generation, "
                    "expires_at_epoch_s, acquired_at_epoch_s, metadata_json, released "
                    "FROM resource_authority_leases "
                    f"WHERE lease_id IN ({placeholders})",
                    ids,
                ).fetchall()
                rows_by_id = {str(row[0]): row for row in fetched}
                if len(rows_by_id) != len(ids):
                    missing = next(lease_id for lease_id in ids if lease_id not in rows_by_id)
                    raise KeyError(missing)

                validated_scope_cuts: set[tuple[str, int, str | None]] = set()
                renewed: list[NoetriumUnit] = []
                for expected, lease_id in zip(leases, ids, strict=True):
                    row = rows_by_id[lease_id]
                    current = self._decode_lease_cached(row)
                    self._require_exact_lease_generation(current, expected)
                    self._require_generation(
                        conn,
                        lease_field(current, "resource_key"),
                        lease_field(current, "generation"),
                    )
                    self._require_live_lease_owner_locked(
                        conn,
                        current,
                        observed_at_epoch_s=observed_at,
                        validated_scope_cuts=validated_scope_cuts,
                    )
                    if lease_field(current, "released"):
                        raise RuntimeError(
                            f"cannot renew released resource lease: {lease_field(current, "lease_id")}"
                        )
                    if (
                        lease_field(current, "expires_at_epoch_s") is not None
                        and lease_field(current, "expires_at_epoch_s") <= observed_at
                    ):
                        raise RuntimeError(
                            f"cannot renew expired resource lease: {lease_field(current, "lease_id")}"
                        )
                    renewed.append(
                        authority_lease(
                            lease_id=lease_field(current, "lease_id"),
                            resource_key=lease_field(current, "resource_key"),
                            holder_key=lease_field(current, "holder_key"),
                            generation=lease_field(current, "generation"),
                            owner_scope=lease_field(current, "owner_scope"),
                            scope_generation=lease_field(current, "scope_generation"),
                            scope_lease_id=lease_field(current, "scope_lease_id"),
                            expires_at_epoch_s=expires,
                            released=False,
                            acquired_at_epoch_s=lease_field(current, "acquired_at_epoch_s"),
                            metadata=lease_field(current, "metadata"),
                            modality=TruthModality.AUTHORIZED,
                        )
                    )
                conn.executemany(
                    "UPDATE resource_authority_leases SET expires_at_epoch_s=? "
                    "WHERE lease_id=? AND generation=?",
                    tuple(
                        (expires, lease_field(row, "lease_id"), lease_field(row, "generation"))
                        for row in renewed
                    ),
                )
                for row in renewed:
                    self._append_lease_renewal_event_locked(
                        conn,
                        row,
                    )
                return tuple(renewed)

    def active_leases(
        self,
        resource_key: str,
        *,
        now: float | None = None,
    ) -> tuple[NoetriumUnit, ...]:
        key = _text(resource_key, "resource key")
        observed_at = self._lease_now(now)
        with self._reader() as conn:
            generation = self._generation_row(conn, key)
            if generation is None:
                return ()
            rows = conn.execute(
                "SELECT lease_id, resource_key, holder_key, generation, "
                "expires_at_epoch_s, acquired_at_epoch_s, metadata_json, released "
                "FROM resource_authority_leases "
                "WHERE resource_key=? AND generation=? AND released=0 "
                "ORDER BY lease_id",
                (key, generation),
            ).fetchall()
        return tuple(
            lease
            for lease in (self._decode_lease(row) for row in rows)
            if lease_live_at(lease, observed_at, current_generation=generation)
        )

    def fence_if_no_live_leases(
        self,
        resource_key: str,
        *,
        holder_key: str,
        excluding_leases: tuple[NoetriumUnit, ...] = (),
        now: float | None = None,
    ) -> NoetriumUnit:
        """Atomically prove zero foreign consumers and close next-generation admission.

        The returned exclusive claim is the retirement gate. It must remain
        held until the old physical closure is observed absent, then be released
        to reopen lease admission on the already-advanced generation.
        """
        key = _text(resource_key, "resource key")
        holder = _text(holder_key, "retirement holder")
        if type(excluding_leases) is not tuple or any(
            not is_authority_lease(row) for row in excluding_leases
        ):
            raise TypeError("lease exclusions must be tuple[NoetriumUnit, ...]")
        exclusion_keys = tuple(
            (lease_field(row, "lease_id"), lease_field(row, "resource_key"), lease_field(row, "holder_key"), lease_field(row, "generation"))
            for row in excluding_leases
        )
        if len(set(exclusion_keys)) != len(exclusion_keys):
            raise ValueError("lease exclusions must be unique")
        if any(lease_field(row, "resource_key") != key for row in excluding_leases):
            raise ValueError("lease exclusion crossed resource identity")
        observed_at = self._lease_now(now)
        excluded = frozenset(exclusion_keys)
        platform_scope_generation = self.ensure_scope_generation(PLATFORM_SCOPE)
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource zero-consumer fence",
            ):
                current = self._generation_row(conn, key)
                if current is None:
                    raise KeyError(key)
                rows = conn.execute(
                    "SELECT lease_id, resource_key, holder_key, generation, "
                    "expires_at_epoch_s, acquired_at_epoch_s, metadata_json, released "
                    "FROM resource_authority_leases "
                    "WHERE resource_key=? AND generation=? AND released=0",
                    (key, current),
                ).fetchall()
                live = tuple(
                    lease
                    for lease in (self._decode_lease(row) for row in rows)
                    if (
                        lease_field(lease, "lease_id"),
                        lease_field(lease, "resource_key"),
                        lease_field(lease, "holder_key"),
                        lease_field(lease, "generation"),
                    ) not in excluded
                    and lease_live_at(lease,
                        observed_at,
                        current_generation=current,
                    )
                )
                if live:
                    raise RuntimeError(
                        "resource generation still has live consumers: "
                        + ",".join(str(lease_field(row, "lease_id")) for row in live)
                    )
                next_generation = current + 1
                cursor = conn.execute(
                    "UPDATE resource_authority_generations SET generation=? "
                    "WHERE resource_key=? AND generation=?",
                    (next_generation, key, current),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError(
                        "resource generation fence lost authority"
                    )
                self._append_trace_event_locked(
                    conn,
                    resource_key=key,
                    generation=next_generation,
                    subject=self._resource_event_subject(key, next_generation),
                    operation="generation",
                    phase="retirement-fence",
                    modality=TruthModality.AUTHORIZED,
                    reads=(f"resource:{key}:generation",),
                    writes=(f"resource:{key}:generation",),
                )
                admission_token = "lease-admission:" + key
                gate = resource_claim(
                    claim_id="retirement:" + canonical_digest(
                        {
                            "resource_key": key,
                            "generation": next_generation,
                            "holder_key": holder,
                        }
                    ),
                    resource_key=key,
                    holder_key=holder,
                    generation=next_generation,
                    owner_scope=PLATFORM_SCOPE,
                    scope_generation=platform_scope_generation.generation,
                    scope_lease_id=None,
                    owner_lease_id=None,
                    exclusive=(admission_token,),
                    attributes={"kind": "lease-admission-fence"},
                )
                self._insert_claim_locked(conn, gate)
                gate = self._authorized_claim(gate)
                self._append_claim_event_locked(
                    conn,
                    gate,
                    operation="fence",
                    phase="retirement-gate",
                )
                conn.execute(
                    "DELETE FROM resource_authority_single_flights "
                    "WHERE resource_key=? AND generation<>?",
                    (key, next_generation),
                )
                return gate

    @staticmethod
    def _decode_ticket(row) -> NoetriumUnit:
        return realization_ticket(
            ticket_id=str(row[0]),
            effect_id=str(row[1]),
            realization_key=str(row[2]),
            resource_key=str(row[3]),
            provider_kind=str(row[4]),
            generation=int(row[5]),
            spec_digest=str(row[6]),
            holder_key=str(row[7]),
            state=TicketState(str(row[8])),
        )

    def _ticket(self, conn, ticket_id: str) -> NoetriumUnit:
        row = conn.execute(
            "SELECT ticket_id, effect_id, realization_key, resource_key, "
            "provider_kind, generation, spec_digest, holder_key, state "
            "FROM resource_authority_tickets WHERE ticket_id=?",
            (ticket_id,),
        ).fetchone()
        if row is None:
            raise KeyError(ticket_id)
        return self._decode_ticket(row)

    def ticket(self, ticket_id: str) -> NoetriumUnit:
        key = _text(ticket_id, "ticket id")
        with self._reader() as conn:
            return self._ticket(conn, key)

    def binding_for_physical(
        self,
        provider_kind: str,
        physical_id: str,
    ) -> NoetriumUnit | None:
        """Return the unique live binding for one provider physical identity."""
        kind = _text(provider_kind, "provider kind")
        identity = _text(physical_id, "physical id")
        with self._reader() as conn:
            rows = conn.execute(
                "SELECT resource_key, generation, ticket_id, spec_digest, "
                "provider_kind, physical_id, attributes_json "
                "FROM resource_authority_bindings "
                "WHERE provider_kind=? AND physical_id=? "
                "ORDER BY resource_key, generation LIMIT 2",
                (kind, identity),
            ).fetchall()
        if len(rows) > 1:
            raise RuntimeError(
                "authority contains multiple bindings for physical identity: "
                f"{kind}:{identity}"
            )
        return None if not rows else self._decode_binding(rows[0])

    def current_ticket(self, resource_key: str) -> NoetriumUnit | None:
        """Return the sole live ticket for the current resource generation.

        This is the indexed point-read counterpart of
        ``AuthoritySnapshot.current_ticket_for``. Reconciliation uses it after a
        plan has already established global state so ticket-local physical
        actions do not rebuild and decode the entire Authority snapshot.
        """
        key = _text(resource_key, "resource key")
        with self._reader() as conn:
            rows = conn.execute(
                "SELECT t.ticket_id, t.effect_id, t.realization_key, "
                "t.resource_key, t.provider_kind, t.generation, "
                "t.spec_digest, t.holder_key, t.state "
                "FROM resource_authority_tickets AS t "
                "JOIN resource_authority_generations AS g "
                "ON g.resource_key=t.resource_key "
                "AND g.generation=t.generation "
                "WHERE t.resource_key=? AND t.state<>'retired' "
                "ORDER BY t.ticket_id",
                (key,),
            ).fetchall()
        if len(rows) > 1:
            raise RuntimeError(
                f"authority contains multiple live tickets for {key}"
            )
        return None if not rows else self._decode_ticket(rows[0])

    @staticmethod
    def _encode_realization_spec(spec: ResourceRealizationSpec) -> str:
        if type(spec) is not ResourceRealizationSpec:
            raise TypeError("realization preparation requires ResourceRealizationSpec")
        return strict_finite_json_text(
            {
                "provider_kind": spec.provider_kind,
                "parameters": dict(spec.parameters or {}),
            }
        )

    @staticmethod
    def _decode_realization_spec(raw: object) -> ResourceRealizationSpec:
        if type(raw) is not str or not raw:
            raise RuntimeError("realization ticket has no frozen physical spec")
        document = strict_json_loads(raw)
        if not isinstance(document, dict):
            raise RuntimeError("frozen realization spec is not an object")
        provider_kind = document.get("provider_kind")
        parameters = document.get("parameters")
        if type(provider_kind) is not str or not isinstance(parameters, dict):
            raise RuntimeError("frozen realization spec is malformed")
        return ResourceRealizationSpec(provider_kind, parameters)

    def _ticket_spec(
        self,
        conn,
        ticket: NoetriumUnit,
    ) -> ResourceRealizationSpec:
        row = conn.execute(
            "SELECT spec_json FROM resource_authority_tickets WHERE ticket_id=?",
            (ticket_field(ticket, "ticket_id"),),
        ).fetchone()
        if row is None:
            raise KeyError(ticket_field(ticket, "ticket_id"))
        spec = self._decode_realization_spec(row[0])
        if (
            spec.provider_kind != ticket_field(ticket, "provider_kind")
            or spec.semantic_digest != ticket_field(ticket, "spec_digest")
        ):
            raise RuntimeError("frozen realization spec does not match ticket digest")
        return spec

    def realization_spec(self, ticket_id: str) -> ResourceRealizationSpec:
        key = _text(ticket_id, "ticket id")
        with self._reader() as conn:
            ticket = self._ticket(conn, key)
            return self._ticket_spec(conn, ticket)

    def prepare_realization(
        self,
        *,
        realization_key: str,
        resource_key: str,
        generation: int,
        spec: ResourceRealizationSpec,
        holder_key: str,
    ) -> tuple[NoetriumUnit, bool]:
        realization = _text(realization_key, "realization key")
        resource = _text(resource_key, "resource key")
        if type(spec) is not ResourceRealizationSpec:
            raise TypeError("realization preparation requires ResourceRealizationSpec")
        provider = spec.provider_kind
        digest = spec.semantic_digest
        spec_json = self._encode_realization_spec(spec)
        holder = _text(holder_key, "holder key")
        if type(generation) is not int or generation < 1:
            raise ValueError("ticket generation must be positive")
        ticket_id = canonical_digest(
            {
                "kind": "resource-realization-ticket",
                "realization_key": realization,
                "resource_key": resource,
                "provider_kind": provider,
                "generation": generation,
                "spec_digest": digest,
            }
        )
        effect_id = canonical_digest(
            {
                "kind": "resource-physical-effect",
                "ticket_id": ticket_id,
            }
        )
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource realization prepare",
            ):
                self._require_generation(conn, resource, generation)
                claim = conn.execute(
                    "SELECT 1 FROM resource_authority_claims "
                    "WHERE released=0 AND resource_key=? AND generation=? LIMIT 1",
                    (resource, generation),
                ).fetchone()
                if claim is None:
                    raise RuntimeError(
                        "physical realization requires an admitted current claim: "
                        f"{resource}:{generation}"
                    )
                stale_effect = conn.execute(
                    "SELECT ticket_id FROM resource_authority_tickets "
                    "WHERE resource_key=? AND generation<>? "
                    "AND state IN ('prepared','bound','retiring') LIMIT 1",
                    (resource, generation),
                ).fetchone()
                if stale_effect is not None:
                    raise RuntimeError(
                        "cannot realize a new generation before stale physical "
                        f"generation is retired: {resource}"
                    )
                flight = conn.execute(
                    "SELECT ticket_id, resource_key, generation "
                    "FROM resource_authority_single_flights "
                    "WHERE realization_key=?",
                    (realization,),
                ).fetchone()
                if flight is not None:
                    existing = self._ticket(conn, str(flight[0]))
                    if (
                        str(flight[1]) == resource
                        and int(flight[2]) == generation
                        and ticket_field(existing, "state") is not TicketState.RETIRED
                    ):
                        return existing, False
                    conn.execute(
                        "DELETE FROM resource_authority_single_flights "
                        "WHERE realization_key=?",
                        (realization,),
                    )
                existing_row = conn.execute(
                    "SELECT ticket_id, effect_id, realization_key, resource_key, "
                    "provider_kind, generation, spec_digest, holder_key, state "
                    "FROM resource_authority_tickets WHERE ticket_id=?",
                    (ticket_id,),
                ).fetchone()
                ticket_created = existing_row is None
                if ticket_created:
                    conn.execute(
                        "INSERT INTO resource_authority_tickets"
                        "(ticket_id, effect_id, realization_key, resource_key, "
                        "provider_kind, generation, spec_digest, spec_json, holder_key, state) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'prepared')",
                        (
                            ticket_id,
                            effect_id,
                            realization,
                            resource,
                            provider,
                            generation,
                            digest,
                            spec_json,
                            holder,
                        ),
                    )
                ticket = self._ticket(conn, ticket_id)
                frozen_spec = self._ticket_spec(conn, ticket)
                if frozen_spec.semantic_digest != spec.semantic_digest:
                    raise RuntimeError("realization ticket spec identity drifted")
                conn.execute(
                    "INSERT INTO resource_authority_single_flights"
                    "(realization_key, ticket_id, resource_key, generation, holder_key) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        realization,
                        ticket_field(ticket, "ticket_id"),
                        resource,
                        generation,
                        holder,
                    ),
                )
                if ticket_created:
                    spec_unit = realization_spec_fact(
                        spec.provider_kind,
                        spec.parameters,
                        modality=TruthModality.DECLARED,
                    )
                    self._append_ticket_event_locked(
                        conn,
                        ticket,
                        operation="prepare",
                        phase="single-flight",
                        evidence=(spec_unit,),
                    )
                return ticket, True

    @staticmethod
    def _validate_observation(
        ticket: NoetriumUnit,
        observation: NoetriumUnit,
    ) -> None:
        if not is_resource_observation(observation):
            raise TypeError("authority binding requires resource.observation Unit")
        if truth_modality(observation) is not TruthModality.OBSERVED:
            raise TypeError("authority binding requires observed truth")
        if (
            observation_field(observation, "resource_key") != ticket_field(ticket, "resource_key")
            or observation_field(observation, "generation") != ticket_field(ticket, "generation")
            or observation_field(observation, "ticket_id") != ticket_field(ticket, "ticket_id")
            or observation_field(observation, "spec_digest") != ticket_field(ticket, "spec_digest")
        ):
            raise RuntimeError(
                "physical observation does not match realization ticket"
            )

    def bind(
        self,
        ticket_id: str,
        observation: NoetriumUnit,
    ) -> NoetriumUnit:
        key = _text(ticket_id, "ticket id")
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource realization bind",
            ):
                ticket = self._ticket(conn, key)
                self._require_generation(
                    conn,
                    ticket_field(ticket, "resource_key"),
                    ticket_field(ticket, "generation"),
                )
                resource_key = str(ticket_field(ticket, "resource_key"))
                generation = int(ticket_field(ticket, "generation"))
                claims = tuple(
                    claim
                    for claim in self._active_claims(
                        conn, frozenset({resource_key})
                    )
                    if int(claim_field(claim, "generation")) == generation
                )
                if len(claims) != 1:
                    raise ResourceClaimConflict(
                        "physical binding requires exactly one live claim: "
                        + resource_key
                    )
                self._require_live_claim_owner_locked(
                    conn,
                    claims[0],
                    observed_at_epoch_s=self._lease_now(None),
                )
                self._validate_observation(ticket, observation)
                self._append_observation_event_locked(conn, observation)
                if not observation_field(observation, "exists") or not observation_field(observation, "ready"):
                    raise ResourceObservationNotReady(
                        "only ready existing physical observation may be bound"
                    )
                identity = observation_field(observation, "physical_identity")
                assert identity is not None
                if physical_field(identity, "provider_kind") != ticket_field(ticket, "provider_kind"):
                    raise RuntimeError(
                        "physical provider identity does not match ticket"
                    )
                if ticket_field(ticket, "state") is TicketState.RETIRED:
                    raise RuntimeError("retired ticket cannot be rebound")
                existing = conn.execute(
                    "SELECT resource_key, generation, ticket_id, spec_digest, "
                    "provider_kind, physical_id, attributes_json "
                    "FROM resource_authority_bindings WHERE ticket_id=?",
                    (key,),
                ).fetchone()
                if existing is not None:
                    binding = self._decode_binding(existing)
                    if (
                        binding_field(binding, "resource_key") == ticket_field(ticket, "resource_key")
                        and binding_field(binding, "generation") == ticket_field(ticket, "generation")
                        and binding_field(binding, "spec_digest") == ticket_field(ticket, "spec_digest")
                        and binding_field(binding, "physical_identity") == identity
                    ):
                        return binding
                    raise RuntimeError(
                        "ticket is already bound to different physical identity"
                    )
                conn.execute(
                    "INSERT INTO resource_authority_bindings"
                    "(resource_key, generation, ticket_id, spec_digest, "
                    "provider_kind, physical_id, attributes_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        ticket_field(ticket, "resource_key"),
                        ticket_field(ticket, "generation"),
                        ticket_field(ticket, "ticket_id"),
                        ticket_field(ticket, "spec_digest"),
                        physical_field(identity, "provider_kind"),
                        physical_field(identity, "physical_id"),
                        json.dumps(
                            thaw_json(physical_field(identity, "attributes") or {}),
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    ),
                )
                conn.execute(
                    "UPDATE resource_authority_tickets SET state='bound' "
                    "WHERE ticket_id=?",
                    (key,),
                )
                binding = realization_binding(
                    ticket_field(ticket, "resource_key"),
                    ticket_field(ticket, "generation"),
                    ticket_field(ticket, "ticket_id"),
                    ticket_field(ticket, "spec_digest"),
                    identity,
                )
                bound_ticket = self._ticket(conn, key)
                self._append_ticket_event_locked(
                    conn,
                    bound_ticket,
                    operation="bind",
                    phase="committed",
                )
                self._append_binding_event_locked(
                    conn,
                    binding,
                    operation="bind",
                    phase="committed",
                )
                return binding

    def begin_retire(self, ticket_id: str) -> NoetriumUnit:
        key = _text(ticket_id, "ticket id")
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource realization retire begin",
            ):
                ticket = self._ticket(conn, key)
                if ticket_field(ticket, "state") is TicketState.RETIRED:
                    return ticket
                # The same writer cut linearizes parent retirement and child
                # claim admission: child-first => retirement rejected;
                # retirement-first => future child admission rejected.
                dependent = conn.execute(
                    "SELECT child.claim_id FROM resource_authority_claims AS parent "
                    "JOIN resource_authority_claims AS child "
                    "ON child.released=0 "
                    "AND json_extract(child.attributes_json, '$.attributes.parent_claim_id')=parent.claim_id "
                    "WHERE parent.released=0 AND parent.resource_key=? "
                    "AND parent.generation=? LIMIT 1",
                    (
                        ticket_field(ticket, "resource_key"),
                        ticket_field(ticket, "generation"),
                    ),
                ).fetchone()
                if dependent is not None:
                    raise ResourceClaimConflict(
                        "cannot begin physical retirement while dependent claim remains: "
                        + key
                    )
                conn.execute(
                    "UPDATE resource_authority_tickets SET state='retiring' "
                    "WHERE ticket_id=?",
                    (key,),
                )
                retiring = self._ticket(conn, key)
                self._append_ticket_event_locked(
                    conn,
                    retiring,
                    operation="retire",
                    phase="begun",
                )
                return retiring

    def complete_retire(
        self,
        ticket_id: str,
        observation: NoetriumUnit,
    ) -> NoetriumUnit:
        key = _text(ticket_id, "ticket id")
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="resource realization retire complete",
            ):
                ticket = self._ticket(conn, key)
                if ticket_field(ticket, "state") is TicketState.RETIRED:
                    return ticket
                self._validate_observation(ticket, observation)
                self._append_observation_event_locked(conn, observation)
                if observation_field(observation, "exists") or observation_field(observation, "ready"):
                    raise RuntimeError(
                        "retirement requires an observed-absent physical realization"
                    )
                conn.execute(
                    "DELETE FROM resource_authority_bindings WHERE ticket_id=?",
                    (key,),
                )
                conn.execute(
                    "DELETE FROM resource_authority_single_flights "
                    "WHERE ticket_id=?",
                    (key,),
                )
                conn.execute(
                    "UPDATE resource_authority_tickets SET state='retired' "
                    "WHERE ticket_id=?",
                    (key,),
                )
                retired = self._ticket(conn, key)
                self._append_ticket_event_locked(
                    conn,
                    retired,
                    operation="retire",
                    phase="completed",
                )
                return retired

    @staticmethod
    def _decode_binding(row) -> NoetriumUnit:
        return realization_binding(
            resource_key=str(row[0]),
            generation=int(row[1]),
            ticket_id=str(row[2]),
            spec_digest=str(row[3]),
            physical=physical_identity(
                provider_kind=str(row[4]),
                physical_id=str(row[5]),
                attributes=json.loads(str(row[6])),
            ),
        )

    def _snapshot_from_reader(
        self,
        conn,
        resource_keys: frozenset[str] | None,
        *,
        claims: tuple[NoetriumUnit, ...] | None = None,
    ) -> AuthoritySnapshot:
        params: tuple[str, ...] = (
            () if resource_keys is None else tuple(resource_keys)
        )
        if resource_keys is not None and not resource_keys:
            return AuthoritySnapshot(
                (),
                () if claims is None else claims,
                (),
                (),
                (),
            )

        key_filter = ""
        and_key_filter = ""
        if resource_keys is not None:
            placeholders = ",".join("?" for _ in params)
            key_filter = f" WHERE resource_key IN ({placeholders})"
            and_key_filter = f" AND resource_key IN ({placeholders})"

        generations = tuple(
            AuthorityGeneration(str(row[0]), int(row[1]))
            for row in conn.execute(
                "SELECT resource_key, generation "
                "FROM resource_authority_generations"
                + key_filter
                + " ORDER BY resource_key",
                params,
            ).fetchall()
        )
        if claims is None:
            claims = self._active_claims_cached(conn, resource_keys)
        lease_rows = conn.execute(
            "SELECT lease_id, resource_key, holder_key, generation, "
            "expires_at_epoch_s, acquired_at_epoch_s, metadata_json, released "
            "FROM resource_authority_leases "
            "WHERE released=0"
            + and_key_filter
            + " ORDER BY lease_id",
            params,
        ).fetchall()
        current_leases: dict[
            str, tuple[tuple[object, ...], NoetriumUnit]
        ] = {}
        decoded_leases: list[NoetriumUnit] = []
        for row in lease_rows:
            frozen_row = tuple(row)
            lease = self._decode_lease_cached(frozen_row)
            current_leases[str(frozen_row[0])] = (frozen_row, lease)
            decoded_leases.append(lease)
        if resource_keys is None:
            self._lease_decode_cache = current_leases
        else:
            self._lease_decode_cache.update(current_leases)
        leases = tuple(decoded_leases)
        tickets = tuple(
            self._decode_ticket(row)
            for row in conn.execute(
                "SELECT ticket_id, effect_id, realization_key, resource_key, "
                "provider_kind, generation, spec_digest, holder_key, state "
                "FROM resource_authority_tickets "
                "WHERE state<>'retired'"
                + and_key_filter
                + " ORDER BY ticket_id",
                params,
            ).fetchall()
        )
        bindings = tuple(
            self._decode_binding(row)
            for row in conn.execute(
                "SELECT resource_key, generation, ticket_id, spec_digest, "
                "provider_kind, physical_id, attributes_json "
                "FROM resource_authority_bindings"
                + key_filter
                + " ORDER BY resource_key, generation",
                params,
            ).fetchall()
        )
        return AuthoritySnapshot(
            generations=generations,
            claims=claims,
            leases=leases,
            tickets=tickets,
            bindings=bindings,
        )

    def _snapshot_for_resource_keys(
        self,
        resource_keys: frozenset[str] | None,
    ) -> AuthoritySnapshot:
        if resource_keys is not None:
            if type(resource_keys) is not frozenset:
                raise TypeError("authority snapshot resource_keys must be frozenset")
            if any(type(key) is not str or not key.strip() for key in resource_keys):
                raise ValueError(
                    "authority snapshot resource keys must be non-empty text"
                )
        with self._reader() as conn:
            with sqlite_read_snapshot(conn):
                return self._snapshot_from_reader(conn, resource_keys)

    def snapshot_for_resource_keys(
        self,
        resource_keys: frozenset[str],
    ) -> AuthoritySnapshot:
        """Return one sparse transactionally consistent live Authority cut."""
        if type(resource_keys) is not frozenset or not resource_keys:
            raise ValueError(
                "resource Authority sparse snapshot requires non-empty frozenset"
            )
        return self._snapshot_for_resource_keys(resource_keys)

    def snapshot_for_resource_keys_with_ownership(
        self,
        resource_keys: frozenset[str],
    ) -> AuthoritySnapshot:
        """Return exact live claims plus only their ownership lease closure.

        Unlike ``snapshot_for_resource_keys`` this pays the ownership traversal
        cost and is therefore intended for denial/recovery paths, not ordinary
        admission snapshots.  Claim discovery remains indexed by the requested
        resource keys; unrelated platform ownership is never decoded.
        """
        if type(resource_keys) is not frozenset or not resource_keys:
            raise ValueError(
                "resource Authority ownership snapshot requires non-empty frozenset"
            )
        if any(type(key) is not str or not key.strip() for key in resource_keys):
            raise ValueError(
                "resource Authority ownership keys must be non-empty text"
            )
        with self._reader() as conn:
            with sqlite_read_snapshot(conn):
                claims: list[NoetriumUnit] = []
                for chunk in self._chunked_keys(tuple(sorted(resource_keys))):
                    placeholders = ",".join("?" for _ in chunk)
                    rows = conn.execute(
                        "SELECT claim_id, resource_key, holder_key, generation, "
                        "amounts_json, shared_json, exclusive_json, attributes_json "
                        "FROM resource_authority_claims "
                        "WHERE released=0 AND resource_key IN ("
                        + placeholders
                        + ") ORDER BY claim_id",
                        chunk,
                    ).fetchall()
                    claims.extend(self._decode_claim_cached(row) for row in rows)
                exact_claims = tuple(
                    sorted(
                        claims,
                        key=lambda row: str(claim_field(row, "claim_id")),
                    )
                )
                closure = self._ownership_resource_keys_for_claims_locked(
                    conn, exact_claims
                )
                return self._snapshot_from_reader(
                    conn, closure, claims=exact_claims
                )

    def next_claim_owner_expiry_delay_for_resource_keys(
        self,
        resource_keys: frozenset[str],
    ) -> float | None:
        """Return one Authority-clock timer edge for exact blocked claims.

        Lease expiry changes liveness without writing an Authority commit.  This
        projection is therefore intentionally separate from the commit feed: it
        returns only the nearest ownership boundary for claims on the requested
        resources.  Missing/already-expired ownership requests an immediate
        recheck; unrelated resources are never traversed.
        """
        snapshot = self.snapshot_for_resource_keys_with_ownership(resource_keys)
        now = self._lease_now(None)
        expiries: list[float] = []
        pending: list[str] = []
        seen: set[str] = set()
        relevant_claims = tuple(
            claim for claim in snapshot.claims
            if str(claim_field(claim, "resource_key")) in resource_keys
        )
        for claim in relevant_claims:
            for raw in (
                claim_field(claim, "owner_lease_id"),
                claim_field(claim, "scope_lease_id"),
            ):
                if raw is not None:
                    pending.append(str(raw))
        while pending:
            lease_id = pending.pop()
            if lease_id in seen:
                continue
            seen.add(lease_id)
            lease = snapshot.lease_by_id(lease_id)
            if lease is None or bool(lease_field(lease, "released")):
                return 0.001
            expiry = lease_field(lease, "expires_at_epoch_s")
            if expiry is not None:
                remaining = float(expiry) - now
                if remaining <= 0.0:
                    return 0.001
                expiries.append(float(expiry))
            parent = lease_field(lease, "scope_lease_id")
            if parent is not None:
                pending.append(str(parent))
        if not expiries:
            return None
        return max(0.001, min(expiries) - now)

    def _ownership_resource_keys_for_claims_locked(
        self,
        conn,
        claims: tuple[NoetriumUnit, ...],
    ) -> frozenset[str]:
        """Return the minimal Resource-Authority ownership closure for claims.

        The closure contains every claim owner Scope generation, explicit owner
        lease, and recursive parent Scope lease resource.  Traversal is batched
        by lease-id frontier so cost depends on the selected ownership graph,
        never total platform state.
        """

        resource_keys: set[str] = set()
        pending_lease_ids: set[str] = set()
        visited_lease_ids: set[str] = set()

        for claim in claims:
            resource_keys.add(str(claim_field(claim, "resource_key")))
            resource_keys.add(
                _scope_resource_key(claim_field(claim, "owner_scope"))
            )
            attrs = dict(claim_field(claim, "attributes") or {})
            consumer_resource_key = str(
                attrs.get("consumer_resource_key") or ""
            ).strip()
            if consumer_resource_key:
                resource_keys.add(consumer_resource_key)
            for lease_id in (
                claim_field(claim, "scope_lease_id"),
                claim_field(claim, "owner_lease_id"),
            ):
                if lease_id is not None:
                    pending_lease_ids.add(str(lease_id))

        while pending_lease_ids:
            frontier = tuple(sorted(pending_lease_ids - visited_lease_ids))
            if not frontier:
                break
            visited_lease_ids.update(frontier)
            pending_lease_ids.clear()

            for chunk in self._chunked_keys(frontier):
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    "SELECT lease_id, resource_key, holder_key, generation, "
                    "expires_at_epoch_s, acquired_at_epoch_s, metadata_json, released "
                    "FROM resource_authority_leases "
                    f"WHERE lease_id IN ({placeholders})",
                    chunk,
                ).fetchall()
                for row in rows:
                    lease = self._decode_lease_cached(row)
                    resource_keys.add(str(lease_field(lease, "resource_key")))
                    resource_keys.add(
                        _scope_resource_key(lease_field(lease, "owner_scope"))
                    )
                    parent_scope_lease_id = lease_field(
                        lease,
                        "scope_lease_id",
                    )
                    if (
                        parent_scope_lease_id is not None
                        and str(parent_scope_lease_id)
                        not in visited_lease_ids
                    ):
                        pending_lease_ids.add(str(parent_scope_lease_id))

        return frozenset(resource_keys)

    def snapshot_for_claim_kinds(
        self,
        claim_kinds: frozenset[str],
    ) -> AuthoritySnapshot:
        """Return the exact claim-kind cut plus complete ownership closure.

        Claim discovery uses the live-kind index.  The cut then closes only over
        consumer resources and the recursive Scope/owner-lease ancestry required
        to prove claim liveness.  Unrelated claims/resources are never decoded.
        """

        if type(claim_kinds) is not frozenset or not claim_kinds:
            raise ValueError(
                "resource Authority claim-kind snapshot requires non-empty frozenset"
            )
        kinds = tuple(
            sorted(_text(kind, "claim kind") for kind in claim_kinds)
        )
        placeholders = ",".join("?" for _ in kinds)
        with self._reader() as conn:
            with sqlite_read_snapshot(conn):
                rows = conn.execute(
                    "SELECT claim_id, resource_key, holder_key, generation, "
                    "amounts_json, shared_json, exclusive_json, attributes_json "
                    "FROM resource_authority_claims "
                    "INDEXED BY idx_resource_authority_claims_live_kind_resource "
                    "WHERE released=0 AND "
                    "json_extract(attributes_json, '$.attributes.kind') "
                    f"IN ({placeholders}) "
                    "ORDER BY claim_id",
                    kinds,
                ).fetchall()
                claims = tuple(
                    self._decode_claim_cached(row)
                    for row in rows
                )
                resource_keys = self._ownership_resource_keys_for_claims_locked(
                    conn,
                    claims,
                )
                return self._snapshot_from_reader(
                    conn,
                    resource_keys,
                    claims=claims,
                )

    def snapshot_for_holder(self, holder_key: str) -> AuthoritySnapshot:
        """Return one transactionally consistent live cut for one holder.

        Holder-local recovery uses this instead of rebuilding the global
        Authority snapshot for every realization identity.
        """
        holder = _text(holder_key, "holder key")
        with self._reader() as conn:
            with sqlite_read_snapshot(conn):
                rows = conn.execute(
                    "SELECT claim_id, resource_key, holder_key, generation, "
                    "amounts_json, shared_json, exclusive_json, attributes_json "
                    "FROM resource_authority_claims "
                    "WHERE released=0 AND holder_key=? ORDER BY claim_id",
                    (holder,),
                ).fetchall()
                claims = tuple(self._decode_claim_cached(row) for row in rows)
                resource_keys = frozenset(
                    claim_field(claim, "resource_key") for claim in claims
                )
                return self._snapshot_from_reader(
                    conn,
                    resource_keys,
                    claims=claims,
                )


    def snapshot(self) -> AuthoritySnapshot:
        """Return one global live Authority cut.

        Reconciliation uses a topology-local cut internally for planning, while
        public callers retain the global live-state view.
        """
        return self._snapshot_for_resource_keys(None)


    @staticmethod
    def _reconcile_fingerprint(snapshot, observations, plan) -> str:
        return canonical_digest(
            {
                "generations": [
                    [row.resource_key, row.generation]
                    for row in snapshot.generations
                ],
                "claims": [row.semantic_digest for row in snapshot.claims],
                "leases": [
                    [
                        lease_field(row, "lease_id"),
                        lease_field(row, "resource_key"),
                        lease_field(row, "holder_key"),
                        lease_field(row, "generation"),
                        lease_field(row, "expires_at_epoch_s"),
                        lease_field(row, "released"),
                    ]
                    for row in snapshot.leases
                ],
                "tickets": [
                    [
                        ticket_field(row, "ticket_id"),
                        ticket_field(row, "resource_key"),
                        ticket_field(row, "generation"),
                        ticket_field(row, "spec_digest"),
                        ticket_field(row, "state").value,
                    ]
                    for row in snapshot.tickets
                ],
                "bindings": [
                    [
                        binding_field(row, "resource_key"),
                        binding_field(row, "generation"),
                        binding_field(row, "ticket_id"),
                        binding_field(row, "spec_digest"),
                        physical_field(binding_field(row, "physical_identity"), "provider_kind"),
                        physical_field(binding_field(row, "physical_identity"), "physical_id"),
                    ]
                    for row in snapshot.bindings
                ],
                "observations": [
                    [
                        resource_id,
                        observation_field(row, "resource_key"),
                        observation_field(row, "generation"),
                        observation_field(row, "ticket_id"),
                        observation_field(row, "spec_digest"),
                        observation_field(row, "exists"),
                        observation_field(row, "ready"),
                        None
                        if observation_field(row, "physical_identity") is None
                        else physical_field(
                            observation_field(row, "physical_identity"),
                            "physical_id",
                        ),
                    ]
                    for resource_id, row in sorted(observations.items())
                ],
                "actions": [
                    [
                        row.ordinal,
                        row.kind.value,
                        row.resource_id,
                        row.reference_id,
                    ]
                    for row in plan.actions
                ],
            }
        )

    def reconcile(
        self,
        topology: NoetriumUnit,
        *,
        claim_candidates: Mapping[
            str,
            Callable[[AuthoritySnapshot, int], tuple[NoetriumUnit, ...]],
        ],
        realization_specs: Mapping[
            str,
            Callable[[AuthoritySnapshot], ResourceRealizationSpec],
        ],
        providers: Mapping[str, PhysicalResourceProvider],
        desired_resource_ids: frozenset[str] | None = None,
    ) -> AuthoritySnapshot:
        """Converge one desired resource topology Unit directly through this Authority.

        There is deliberately no ResourceManager/Executor between Graph and
        Authority. Candidate functions are pure placement/admission projections;
        providers are the three-operation physical ISA.
        """
        from .reconciliation import ResourceReconciliationPlanner

        planner = ResourceReconciliationPlanner(topology)
        desired = (
            planner.topology_index.resource_ids
            if desired_resource_ids is None
            else desired_resource_ids
        )
        set_cost_scale("resource_topology_nodes", len(planner.topology_index.resource_ids))
        set_cost_scale("resource_desired_resources", len(desired))
        if type(desired) is not frozenset:
            raise TypeError("desired resource ids must be frozenset")
        if not desired <= planner.topology_index.resource_ids:
            raise ValueError("desired resource set contains unknown graph nodes")
        topology_authority_keys = frozenset(
            planner.topology_index.authority_key(resource_id)
            for resource_id in planner.topology_index.resource_ids
        )
        # One reconcile owns one topology. Recover only claims that can affect
        # this topology; global orphan sweeping remains an explicit maintenance
        # operation and must not be paid by every local realization.
        self.reconcile_orphan_claims_for_resource_keys(
            topology_authority_keys
        )
        unknown_claim_compilers = frozenset(claim_candidates) - planner.topology_index.resource_ids
        unknown_specs = frozenset(realization_specs) - planner.topology_index.resource_ids
        if unknown_claim_compilers or unknown_specs:
            raise ValueError("resource reconciliation inputs contain unknown graph nodes")
        for resource_id in desired:
            if resource_id not in claim_candidates:
                raise ValueError(
                    f"desired resource lacks claim candidate compiler: {resource_id}"
                )
            if planner.topology_index.requires_realization(resource_id) and resource_id not in realization_specs:
                raise ValueError(
                    f"physical resource lacks realization spec compiler: {resource_id}"
                )
        seen: set[str] = set()
        while True:
            add_cost_work("resource_reconcile_rounds", 1)
            # Planning/recovery is topology-local. Unrelated projects/resources
            # cannot affect dependency convergence and must not inflate this cut.
            snapshot = self._snapshot_for_resource_keys(topology_authority_keys)
            observations: dict[str, NoetriumUnit] = {}
            for resource_id in planner.topology_index.resource_ids:
                if not planner.topology_index.requires_realization(resource_id):
                    continue
                key = planner.topology_index.authority_key(resource_id)
                generation = snapshot.generation_for(key)
                if generation is None:
                    continue
                ticket = snapshot.current_ticket_for(key)
                if ticket is None:
                    continue
                provider = providers.get(ticket_field(ticket, "provider_kind"))
                if provider is None:
                    raise KeyError(
                        f"no physical provider for kind: {ticket_field(ticket, "provider_kind")}"
                    )
                reference = self._provider_reference(ticket, snapshot)
                observation = provider.observe(reference)
                self._validate_observation(ticket, observation)
                self.record_observation(observation)
                observations[resource_id] = observation
                add_cost_work("resource_provider_observations", 1)

            plan = planner.plan(
                snapshot,
                observations,
                desired_resource_ids=desired,
            )
            add_cost_work("resource_reconcile_actions", len(plan.actions))
            if plan.converged:
                # Reconciliation owns one topology, so its result is the exact
                # live Authority cut for that topology. Global cuts remain
                # available explicitly through snapshot() and are still used
                # where placement must observe unrelated competitors.
                return self._snapshot_for_resource_keys(
                    topology_authority_keys
                )
            fingerprint = self._reconcile_fingerprint(
                snapshot,
                observations,
                plan,
            )
            if fingerprint in seen:
                raise RuntimeError(
                    "resource reconciliation reached a non-progress fixed point"
                )
            seen.add(fingerprint)

            claim_actions = tuple(
                action
                for action in plan.actions
                if action.kind is ReconcileActionKind.ACQUIRE_CLAIM
            )
            bundled_claim_resources: frozenset[str] = frozenset()
            if claim_actions:
                advance_actions = tuple(
                    action
                    for action in plan.actions
                    if action.kind is ReconcileActionKind.ADVANCE_GENERATION
                )
                # Fresh topology construction may discover several resources
                # without generation rows in one planner cut. Generation epochs
                # carry no capacity, so establish only those epochs first and
                # replan before acquiring any claim. This creates the stable cut
                # required for atomic bundle admission.
                if advance_actions and all(
                    snapshot.generation_for(
                        planner.topology_index.authority_key(action.resource_id)
                    )
                    is None
                    for action in advance_actions
                ):
                    self._ensure_generations(
                        tuple(
                            planner.topology_index.authority_key(action.resource_id)
                            for action in advance_actions
                        )
                    )
                    continue

                destructive_kinds = {
                    ReconcileActionKind.ADVANCE_GENERATION,
                    ReconcileActionKind.RETIRE,
                    ReconcileActionKind.CONFIRM_ABSENT,
                    ReconcileActionKind.RELEASE_CLAIM,
                }
                has_destructive_work = any(
                    action.kind in destructive_kinds for action in plan.actions
                )
                if not has_destructive_work:
                    current = self.snapshot()
                    candidate_groups: list[tuple[NoetriumUnit, ...]] = []
                    for action in claim_actions:
                        resource_id = action.resource_id
                        key = planner.topology_index.authority_key(resource_id)
                        generation = current.generation_for(key)
                        if generation is None:
                            raise RuntimeError(
                                f"bundle claim admission lacks authority generation: {key}"
                            )
                        candidates = claim_candidates[resource_id](
                            current, generation.generation
                        )
                        if type(candidates) is not tuple or not candidates:
                            raise ResourceClaimConflict(
                                f"resource claim compiler produced no candidates: {resource_id}"
                            )
                        for claim in candidates:
                            if (
                                claim_field(claim, "resource_key") != key
                                or claim_field(claim, "generation")
                                != generation.generation
                            ):
                                raise RuntimeError(
                                    "resource claim compiler crossed authority identity/generation"
                                )
                        candidate_groups.append(candidates)
                    try:
                        self.admit_bundle(tuple(candidate_groups))
                    except ResourceClaimConflict:
                        refreshed = self.snapshot()
                        if refreshed == current:
                            raise
                        add_cost_work(
                            "resource_admission_conflict_replans", 1
                        )
                        seen.discard(fingerprint)
                        continue
                    bundled_claim_resources = frozenset(
                        action.resource_id for action in claim_actions
                    )

            for action in plan.actions:
                resource_id = action.resource_id
                key = planner.topology_index.authority_key(resource_id)
                if action.kind is ReconcileActionKind.ADVANCE_GENERATION:
                    current_generation = snapshot.generation_for(key)
                    if current_generation is None:
                        self.ensure_generation(key)
                    else:
                        self.advance_generation(key)
                    continue

                if action.kind is ReconcileActionKind.ACQUIRE_CLAIM:
                    if resource_id in bundled_claim_resources:
                        continue
                    current = self.snapshot()
                    generation = current.generation_for(key)
                    if generation is None:
                        raise RuntimeError(
                            f"claim admission lacks authority generation: {key}"
                        )
                    candidates = claim_candidates[resource_id](
                        current,
                        generation.generation,
                    )
                    if type(candidates) is not tuple or not candidates:
                        raise ResourceClaimConflict(
                            f"resource claim compiler produced no candidates: {resource_id}"
                        )
                    for claim in candidates:
                        if (
                            claim_field(claim, "resource_key") != key
                            or claim_field(claim, "generation") != generation.generation
                        ):
                            raise RuntimeError(
                                "resource claim compiler crossed authority identity/generation"
                            )
                    try:
                        self.admit_first(candidates)
                    except ResourceClaimConflict:
                        # Placement candidates are compiled optimistically from a
                        # global Authority cut, then admitted under the writer
                        # transaction. Another reconciler may legitimately claim
                        # one of those candidates in between. Retry only when
                        # Authority truth actually changed; an unchanged cut is a
                        # real incompatibility and remains fail-close.
                        refreshed = self.snapshot()
                        if refreshed == current:
                            raise
                        add_cost_work("resource_admission_conflict_replans", 1)
                        seen.discard(fingerprint)
                        break
                    continue

                if action.kind is ReconcileActionKind.PREPARE:
                    current = self._snapshot_for_resource_keys(
                        topology_authority_keys
                    )
                    generation = current.generation_for(key)
                    if generation is None:
                        raise RuntimeError(
                            f"realization prepare lacks authority generation: {key}"
                        )
                    claims = current.current_claims_for(key)
                    if len(claims) != 1:
                        raise RuntimeError(
                            "physical realization requires exactly one current claim"
                        )
                    spec = realization_specs[resource_id](current)
                    if type(spec) is not ResourceRealizationSpec:
                        raise TypeError(
                            "realization spec compiler must return ResourceRealizationSpec"
                        )
                    realization_key = canonical_digest(
                        {
                            "resource_key": key,
                            "generation": generation.generation,
                            "spec_digest": spec.semantic_digest,
                            "claim_digest": claims[0].semantic_digest,
                        }
                    )
                    self.prepare_realization(
                        realization_key=realization_key,
                        resource_key=key,
                        generation=generation.generation,
                        spec=spec,
                        holder_key=claim_field(claims[0], "holder_key"),
                    )
                    continue

                if action.kind in {
                    ReconcileActionKind.REALIZE,
                    ReconcileActionKind.BIND,
                }:
                    ticket = (
                        self.ticket(action.reference_id)
                        if action.reference_id is not None
                        else self.current_ticket(key)
                    )
                    if ticket is None:
                        raise RuntimeError(
                            f"physical action lacks realization ticket: {resource_id}"
                        )
                    provider = providers.get(ticket_field(ticket, "provider_kind"))
                    if provider is None:
                        raise KeyError(
                            f"no physical provider for kind: {ticket_field(ticket, "provider_kind")}"
                        )
                    ownership_cut = self._snapshot_for_resource_keys(
                        topology_authority_keys
                    )
                    live_claims = ownership_cut.current_claims_for(key)
                    if (
                        len(live_claims) != 1
                        or not self.claim_owner_live(live_claims[0])
                    ):
                        self._retire_ticket_for_lost_ownership(
                            ticket=ticket,
                            provider=provider,
                            snapshot=ownership_cut,
                        )
                        break
                    if action.kind is ReconcileActionKind.REALIZE:
                        # PREPARE freezes the exact physical spec durably. Never
                        # recompile after a ticket exists: crash recovery must replay
                        # the same effect bytes, not merely an equal-looking plan.
                        spec = self.realization_spec(ticket_field(ticket, "ticket_id"))
                        identity = provider.realize(spec.parameters or {}, ticket)
                        if physical_field(identity, "provider_kind") != ticket_field(ticket, "provider_kind"):
                            raise RuntimeError(
                                "provider returned a foreign physical identity"
                            )
                        # Physical realization may be slow. Ownership must still
                        # be live *after* the effect completes before a later BIND
                        # is allowed to publish it as Authority truth.
                        post_cut = self._snapshot_for_resource_keys(
                            topology_authority_keys
                        )
                        post_claims = post_cut.current_claims_for(key)
                        if (
                            len(post_claims) != 1
                            or not self.claim_owner_live(post_claims[0])
                        ):
                            self._retire_ticket_for_lost_ownership(
                                ticket=ticket,
                                provider=provider,
                                snapshot=post_cut,
                                reference=identity,
                            )
                            break
                    else:
                        self.bind(ticket_field(ticket, "ticket_id"), provider.observe(ticket))
                    continue

                if action.kind is ReconcileActionKind.RETIRE:
                    if action.reference_id is None:
                        raise RuntimeError("retire action requires ticket reference")
                    ticket = self.begin_retire(action.reference_id)
                    provider = providers.get(ticket_field(ticket, "provider_kind"))
                    if provider is None:
                        raise KeyError(
                            f"no physical provider for kind: {ticket_field(ticket, "provider_kind")}"
                        )
                    current = self._snapshot_for_resource_keys(
                        topology_authority_keys
                    )
                    reference = self._provider_reference(ticket, current)
                    observation = provider.retire(reference, ticket)
                    self._validate_observation(ticket, observation)
                    self.record_observation(observation)
                    if observation_field(observation, "exists"):
                        # Multi-step physical retirement made observable progress.
                        # Do not execute CONFIRM_ABSENT or release ownership in
                        # this stale plan; replan from the new observed checkpoint.
                        break
                    continue

                if action.kind is ReconcileActionKind.CONFIRM_ABSENT:
                    if action.reference_id is None:
                        raise RuntimeError(
                            "confirm-absent action requires ticket reference"
                        )
                    try:
                        ticket = self.ticket(action.reference_id)
                    except KeyError as exc:
                        raise RuntimeError(
                            "confirm-absent ticket disappeared from Authority"
                        ) from exc
                    provider = providers.get(ticket_field(ticket, "provider_kind"))
                    if provider is None:
                        raise KeyError(
                            f"no physical provider for kind: {ticket_field(ticket, "provider_kind")}"
                        )
                    current = self._snapshot_for_resource_keys(
                        topology_authority_keys
                    )
                    reference = self._provider_reference(ticket, current)
                    observation = provider.observe(reference)
                    self._validate_observation(ticket, observation)
                    self.record_observation(observation)
                    if observation_field(observation, "exists"):
                        break
                    self.complete_retire(
                        ticket_field(ticket, "ticket_id"),
                        observation,
                    )
                    continue

                if action.kind is ReconcileActionKind.RELEASE_CLAIM:
                    if action.reference_id is None:
                        raise RuntimeError(
                            "release-claim action requires claim reference"
                        )
                    self.release_claim(action.reference_id)
                    continue

                raise RuntimeError(
                    f"unsupported resource reconcile action: {action.kind.value}"
                )


__all__ = ["UniversalResourceAuthority"]
