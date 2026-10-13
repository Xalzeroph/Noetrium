"""Cross-process linearized service accounting using the existing VTC/LAS scheduler.

The scheduling event journal owns a separate durable SQLite transaction lane
from Resource Authority: distinct dynamically authoritative truths must not
block one another's physical writer permits.
The algorithm is exactly UnifiedSchedulingAuthority; this class adds the
transaction/catch-up boundary, not an alternative fairness policy.
"""
from __future__ import annotations

from collections.abc import Iterable
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
from threading import Event, Lock, RLock, local

from noetrium_platform.foundation.kernel.kernel.durability.sqlite import (
    DurableSQLiteReaderOwner, DurableSQLiteWriterOwner,
    durable_sqlite_connection, durable_sqlite_reader,
    immediate_sqlite_transaction, sqlite_read_snapshot,
)
from noetrium_platform.foundation.kernel.concurrency.scheduling.api import (
    SchedulingCandidate,
)
from .unified import UnifiedSchedulingAuthority

_SCHEMA = """
CREATE TABLE IF NOT EXISTS unified_scheduling_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    operation TEXT NOT NULL CHECK (
        operation IN ('grant','completion','rollback','release_flow','release_resource')
    ),
    payload TEXT NOT NULL
);
"""
_CHECKPOINT_SCHEMA = """
CREATE TABLE IF NOT EXISTS unified_scheduling_checkpoint (
    id INTEGER PRIMARY KEY CHECK (id=1),
    sequence INTEGER NOT NULL CHECK (sequence>=0),
    payload TEXT NOT NULL,
    sha256 TEXT NOT NULL
);
"""
# Checkpoint is a disposable, transactionally derived projection of the one
# authoritative event journal. A bounded suffix always remains replayable.
_CHECKPOINT_INTERVAL = 2048


@dataclass(slots=True)
class _PendingTransition:
    """One producer-owned grant/completion receipt and writer leadership baton."""

    operation: str
    fields: dict
    wakeup: Event = field(default_factory=Event)
    leading: bool = False
    completed: bool = False
    result: int | None = None
    failure: BaseException | None = None


class DurableUnifiedSchedulingAuthority(UnifiedSchedulingAuthority):
    """The same scheduling algorithm with a single shared durable cut.

    The ledger serializes grants, completions and rollbacks globally. Each
    process replays only events newer than its local materialized view. The
    local per-entity indices remain disposable and are never an Authority.
    """

    def __init__(self, authority_path: str | Path) -> None:
        super().__init__()
        self._ledger_path = Path(authority_path)
        self._cut_lock = RLock()
        self._applied = 0
        self._checkpoint_cut = 0
        self._read_scope = local()
        self._write_scope = local()
        self._recorded_flow_coordinates: dict[str, set[tuple[str | None, str | None]]] = {}
        self._writers = DurableSQLiteWriterOwner(
            self._ledger_path, timeout_seconds=30,
        )
        self._readers = DurableSQLiteReaderOwner(
            self._ledger_path, timeout_seconds=30,
        )
        self._reader_data_version: int | None = None
        self._closed = False
        # Grant and completion share one mechanical writer handoff. This
        # queue is not a fairness authority: the committed service ledger is.
        # Producers drive finite cuts with no extra worker or batching timer.
        self._transition_lock = Lock()
        self._transition_queue: deque[_PendingTransition] = deque()
        self._transition_draining = False
        # A warm Runtime Fabric has already installed both tables. Merely
        # attaching a new consumer must not acquire the global SQLite write
        # permit, which may be held by another active research run. The
        # read-only probe is authoritative SQLite schema introspection; a
        # first-launch database still creates both tables in one transaction.
        existing = False
        if self._ledger_path.is_file():
            with durable_sqlite_reader(
                self._ledger_path, timeout_seconds=30,
            ) as conn:
                existing = {
                    row[0] for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name IN ('unified_scheduling_events',"
                        "'unified_scheduling_checkpoint')"
                    )
                } == {"unified_scheduling_events", "unified_scheduling_checkpoint"}
        if not existing:
            with durable_sqlite_connection(self._ledger_path, timeout_seconds=30) as conn:
                with immediate_sqlite_transaction(
                    conn, timeout_seconds=30, label="global scheduler schema"
                ):
                    conn.execute(_SCHEMA)
                    conn.execute(_CHECKPOINT_SCHEMA)

    def _reset_view(self) -> None:
        # The only lasting fact is the durable journal. Any failed transaction
        # invalidates the local materialized index; replay from genesis.
        UnifiedSchedulingAuthority.__init__(self)
        self._applied = 0
        self._checkpoint_cut = 0
        self._read_scope = local()
        self._recorded_flow_coordinates = {}
        self._reader_data_version = None

    def _encode_checkpoint(self) -> str:
        """Freeze the existing scheduling state, not a second fairness truth."""
        def states(mapping):
            return [
                [
                    key, list(state.parent), state.in_flight,
                    state.service_quanta, state.reserved_service_quanta,
                    state.last_grant, state.last_completion,
                    state.retire_requested,
                ]
                for key in sorted(mapping)
                for state in (mapping[key],)
            ]

        return json.dumps(
            {
                "schema": "noetrium.unified-scheduling-checkpoint.v1",
                "sequence": self._applied,
                "grant_sequence": self._grant_sequence,
                "tenants": states(self._tenant_states),
                "resources": states(self._resource_states),
                "flows": states(self._flow_states),
                "coordinates": [
                    [flow_id, [[tenant, resource] for tenant, resource in
                               sorted(values, key=lambda row: (str(row[0]), str(row[1])))]]
                    for flow_id, values in sorted(self._recorded_flow_coordinates.items())
                ],
            },
            sort_keys=True, separators=(",", ":"),
        )

    def _restore_checkpoint(self, payload: str, sequence: int, digest: str) -> None:
        if sha256(payload.encode("utf-8")).hexdigest() != digest:
            raise RuntimeError("global scheduling checkpoint digest drift")
        try:
            record = json.loads(payload)
            if type(record) is not dict or set(record) != {
                "schema", "sequence", "grant_sequence", "tenants",
                "resources", "flows", "coordinates",
            }:
                raise ValueError("checkpoint fields drifted")
            if (record["schema"] != "noetrium.unified-scheduling-checkpoint.v1"
                    or type(record["sequence"]) is not int
                    or record["sequence"] != sequence
                    or type(record["grant_sequence"]) is not int
                    or record["grant_sequence"] < 0):
                raise ValueError("checkpoint identity drifted")

            # Validate the entire payload before modifying the materialized cut.
            staged = []
            for kind, label in (("tenant", "tenants"), ("resource", "resources"),
                                ("flow", "flows")):
                rows = record[label]
                if type(rows) is not list:
                    raise ValueError("checkpoint state rows must be a list")
                seen = set()
                for row in rows:
                    if type(row) is not list or len(row) != 8:
                        raise ValueError("checkpoint state has invalid arity")
                    key, parent, active, service, reserved, grant, completion, retired = row
                    if (type(key) is not str or not key
                            or key in seen or type(parent) is not list
                            or any(type(item) is not str for item in parent)
                            or any(type(x) is not int for x in
                                   (active, service, reserved, grant, completion))
                            or min(active, service, reserved) < 0
                            or grant < -1 or completion < -1
                            or type(retired) is not bool):
                        raise ValueError("checkpoint scheduling state is invalid")
                    seen.add(key)
                    staged.append((kind, key, tuple(parent), active, service,
                                   reserved, grant, completion, retired))
            coordinates = record["coordinates"]
            if type(coordinates) is not list:
                raise ValueError("checkpoint coordinates are invalid")
            parsed_coordinates = {}
            for entry in coordinates:
                if (type(entry) is not list or len(entry) != 2
                        or type(entry[0]) is not str or not entry[0]
                        or entry[0] in parsed_coordinates
                        or type(entry[1]) is not list):
                    raise ValueError("checkpoint flow coordinates are invalid")
                values = set()
                for pair in entry[1]:
                    if (type(pair) is not list or len(pair) != 2
                            or any(value is not None and type(value) is not str
                                   for value in pair)):
                        raise ValueError("checkpoint flow coordinate is invalid")
                    values.add(tuple(pair))
                parsed_coordinates[entry[0]] = values
        except (TypeError, ValueError, KeyError) as exc:
            raise RuntimeError("global scheduling checkpoint cannot be decoded") from exc

        UnifiedSchedulingAuthority.__init__(self)
        for kind, key, parent, active, service, reserved, grant, completion, retired in staged:
            state = self._entity(kind=kind, key=key, parent=parent)
            state.in_flight = active
            state.service_quanta = service
            state.reserved_service_quanta = reserved
            state.last_grant = grant
            state.last_completion = completion
            state.retire_requested = retired
            state.frontier.publish(state)
        self._grant_sequence = record["grant_sequence"]
        self._recorded_flow_coordinates = parsed_coordinates
        self._applied = sequence
        self._checkpoint_cut = sequence

    def _load_checkpoint(self, conn) -> None:
        row = next(iter(conn.execute(
            "SELECT sequence,payload,sha256 FROM unified_scheduling_checkpoint "
            "WHERE id=1"
        )), None)
        if row is None or int(row[0]) <= self._applied:
            return
        last = next(iter(conn.execute(
            "SELECT MAX(sequence) FROM unified_scheduling_events"
        )))[0]
        if last is None or int(row[0]) > int(last):
            raise RuntimeError("global scheduling checkpoint exceeds journal cut")
        self._restore_checkpoint(str(row[1]), int(row[0]), str(row[2]))

    def _maybe_checkpoint(self, conn) -> None:
        # At least one event per live entity between whole-state snapshots:
        # O(S) checkpoint work is amortized across Omega(S) transitions,
        # while cold recovery remains O(S + trailing_events).
        interval = max(
            _CHECKPOINT_INTERVAL,
            len(self._tenant_states)
            + len(self._resource_states)
            + len(self._flow_states),
        )
        if self._applied - self._checkpoint_cut < interval:
            return
        row = conn.execute(
            "SELECT sequence FROM unified_scheduling_checkpoint WHERE id=1"
        ).fetchone()
        self._checkpoint_cut = 0 if row is None else int(row[0])
        if self._applied - self._checkpoint_cut < interval:
            return
        payload = self._encode_checkpoint()
        conn.execute(
            "INSERT INTO unified_scheduling_checkpoint(id,sequence,payload,sha256) "
            "VALUES (1,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "sequence=excluded.sequence,payload=excluded.payload,"
            "sha256=excluded.sha256",
            (self._applied, payload, sha256(payload.encode("utf-8")).hexdigest()),
        )
        self._checkpoint_cut = self._applied

    def _catch_up(self, conn) -> None:
        # Cold recovery may replay millions of committed grants. SQLite
        # streaming preserves the exact same transactional snapshot and
        # contiguous sequence checks, without materializing the entire
        # historical journal as Python tuples in memory.
        self._load_checkpoint(conn)
        rows = conn.execute(
            "SELECT sequence, operation, payload FROM unified_scheduling_events "
            "WHERE sequence>? ORDER BY sequence",
            (self._applied,),
        )
        for sequence, operation, payload in rows:
            if int(sequence) != self._applied + 1:
                raise RuntimeError("global scheduling event journal sequence is not contiguous")
            fields = json.loads(payload)
            if operation == "grant":
                super().record_grant(**fields)
                self._recorded_flow_coordinates.setdefault(
                    fields["flow_id"], set(),
                ).add((fields.get("tenant_id"), fields.get("resource_id")))
            elif operation == "completion":
                super().record_completion(**fields)
            elif operation == "rollback":
                super().rollback_grant(**fields)
            elif operation == "release_flow":
                # Early persisted release events recorded only flow_id.
                # Recover the unique physical accounting identity from the
                # preceding *durable grants*, never from a guessed name or
                # current in-memory owner. Ambiguous identities fail-close.
                if "tenant_id" not in fields:
                    coordinates = self._recorded_flow_coordinates.get(
                        fields["flow_id"], set(),
                    )
                    if len(coordinates) > 1:
                        raise RuntimeError(
                            "historic global scheduling release has ambiguous "
                            "flow identity: " + fields["flow_id"]
                        )
                    tenant, resource = (
                        next(iter(coordinates)) if coordinates else (None, None)
                    )
                    fields = {
                        **fields,
                        "tenant_id": tenant,
                        "resource_id": resource,
                    }
                super().release_flow(**fields)
            elif operation == "release_resource":
                super().release_resource(**fields)
            else:
                raise RuntimeError("unknown global scheduling event: " + str(operation))
            self._applied = int(sequence)

    @contextmanager
    def _owned_writer_cut(self):
        if getattr(self._write_scope, "inside", False):
            raise RuntimeError("scheduling writer cannot synchronously reenter its own cut")
        self._write_scope.inside = True
        try:
            yield
        finally:
            self._write_scope.inside = False

    def _mutation(self, operation: str, fields: dict):
        with self._owned_writer_cut(), self._cut_lock:
            if self._closed:
                raise RuntimeError("durable scheduling authority is closed")
            try:
                # Catch up outside the exclusive writer transaction first:
                # cold processes must not hold the physical SQLite write
                # permit while replaying other processes' historical events.
                self._read_cut()
                with self._writers.session() as conn:
                    with immediate_sqlite_transaction(
                        conn, timeout_seconds=30,
                        label="global scheduling " + operation,
                    ):
                        self._catch_up(conn)
                        if operation == "grant":
                            result = super().record_grant(**fields)
                            # The committed writer's projection must contain
                            # the same flow provenance as a cold replay. It is
                            # needed to resolve old bare release records after
                            # a checkpoint without scanning pre-cut history.
                            self._recorded_flow_coordinates.setdefault(
                                fields["flow_id"], set(),
                            ).add((fields.get("tenant_id"), fields.get("resource_id")))
                        elif operation == "completion":
                            result = super().record_completion(**fields)
                        elif operation == "rollback":
                            result = super().rollback_grant(**fields)
                        elif operation == "release_flow":
                            result = super().release_flow(**fields)
                        elif operation == "release_resource":
                            result = super().release_resource(**fields)
                        else:
                            raise RuntimeError("unsupported scheduling transition")
                        cursor = conn.execute(
                            "INSERT INTO unified_scheduling_events(operation,payload) "
                            "VALUES (?,?)",
                            (operation, json.dumps(fields, sort_keys=True, separators=(",", ":"))),
                        )
                        self._applied = int(cursor.lastrowid)
                        self._maybe_checkpoint(conn)
                        return result
            except BaseException:
                self._reset_view()
                raise

    def _group_transition(self, operation: str, fields: dict) -> int | None:
        # Waiting for a receipt that only this same producer could commit is a
        # self-dependency, not cross-thread contention. Reject before enqueue.
        if getattr(self._write_scope, "inside", False):
            raise RuntimeError("scheduling writer cannot synchronously reenter its own cut")
        pending = _PendingTransition(operation, fields)
        with self._transition_lock:
            self._transition_queue.append(pending)
            if not self._transition_draining:
                self._transition_draining = True
                pending.leading = True
                pending.wakeup.set()
        while True:
            pending.wakeup.wait()
            with self._transition_lock:
                if pending.completed:
                    if pending.failure is not None:
                        raise pending.failure
                    return pending.result
                if not pending.leading:
                    raise RuntimeError("scheduling receipt woke without a writer handoff")
                pending.leading = False
                pending.wakeup.clear()
            self._drain_transition_cut(operation)

    def _drain_transition_cut(self, leader_operation: str) -> None:
        """Commit one finite FIFO cut, then hand the writer to its next producer.

        New arrivals can join while cold replay/BEGIN performs useful work.
        Once captured, the cut never expands while executing its SQL: an
        unbounded request stream cannot monopolize the writer or keep an
        already-committed leader waiting for later transactions. Grant and
        completion receipts may share FULL durability without changing their
        order, accounting law, or synchronous acknowledgement boundary.
        """
        batch: tuple[_PendingTransition, ...] = ()
        try:
            with self._owned_writer_cut(), self._cut_lock:
                if self._closed:
                    raise RuntimeError("durable scheduling authority is closed")
                self._read_cut()
                with self._writers.session() as conn:
                    with immediate_sqlite_transaction(
                        conn, timeout_seconds=30,
                        label="global scheduling " + leader_operation + " group",
                    ):
                        self._catch_up(conn)
                        with self._transition_lock:
                            batch = tuple(self._transition_queue)
                            self._transition_queue.clear()
                        for item in batch:
                            try:
                                if item.operation == "grant":
                                    item.result = super().record_grant(**item.fields)
                                elif item.operation == "completion":
                                    super().record_completion(**item.fields)
                                else:
                                    raise RuntimeError("unknown scheduling group transition")
                            except (TypeError, ValueError, RuntimeError) as exc:
                                # Base validation completes before mutating any
                                # hierarchy counters. Isolate logical rejection;
                                # physical SQL/commit failures reject the cut.
                                item.failure = exc
                                continue
                            if item.operation == "grant":
                                self._recorded_flow_coordinates.setdefault(
                                    item.fields["flow_id"], set(),
                                ).add((item.fields.get("tenant_id"), item.fields.get("resource_id")))
                            cursor = conn.execute(
                                "INSERT INTO unified_scheduling_events(operation,payload) VALUES (?,?)",
                                (item.operation, json.dumps(item.fields, sort_keys=True, separators=(",", ":"))),
                            )
                            self._applied = int(cursor.lastrowid)
                        self._maybe_checkpoint(conn)
        except BaseException as exc:
            with self._cut_lock:
                self._reset_view()
            with self._transition_lock:
                stranded = tuple(self._transition_queue)
                self._transition_queue.clear()
                self._transition_draining = False
                for item in (*batch, *stranded):
                    item.result = None
                    item.failure = exc
                    item.completed = True
                    item.wakeup.set()
        else:
            with self._transition_lock:
                for item in batch:
                    item.completed = True
                    item.wakeup.set()
                if self._transition_queue:
                    successor = self._transition_queue[0]
                    successor.leading = True
                    successor.wakeup.set()
                else:
                    self._transition_draining = False

    def _read_cut(self) -> None:
        if getattr(self._read_scope, "inside", False):
            return
        with self._cut_lock:
            if self._closed:
                raise RuntimeError("durable scheduling authority is closed")
            if getattr(self._read_scope, "inside", False):
                return
            with self._readers.session() as conn:
                with sqlite_read_snapshot(conn):
                    # SQLite's connection-local data_version invalidates this
                    # disposable projection on commits from *any* process.
                    # It includes checkpoint repairs/corruption that would be
                    # invisible to an events-only MAX(sequence) shortcut.
                    # This is a FRESH read transaction, never a stale in-memory
                    # fairness claim. A writer transaction still calls catch_up
                    # under BEGIN IMMEDIATE independently of this fast path.
                    version = int(conn.execute("PRAGMA data_version").fetchone()[0])
                    if version != self._reader_data_version:
                        self._catch_up(conn)
                        self._reader_data_version = version

    def close(self) -> None:
        """Retire the process-owned writer after every scheduling domain closes."""
        with self._cut_lock:
            if self._closed:
                return
            self._readers.close()
            self._writers.close()
            self._closed = True

    def record_grant(
        self, *, tenant_id: str | None, flow_id: str,
        resource_id: str | None = None, permit_count: int = 1,
        reserved_service_quanta: int = 0,
    ) -> int:
        result = self._group_transition("grant", dict(
            tenant_id=tenant_id, flow_id=flow_id, resource_id=resource_id,
            permit_count=permit_count,
            reserved_service_quanta=reserved_service_quanta,
        ))
        if result is None:
            raise RuntimeError("durable scheduling grant lost result")
        return result

    def record_completion(
        self, *, tenant_id: str | None, flow_id: str,
        service_quanta: int, resource_id: str | None = None,
        permit_count: int = 1, reserved_service_quanta: int = 0,
    ) -> None:
        self._group_transition("completion", dict(
            tenant_id=tenant_id, flow_id=flow_id,
            service_quanta=service_quanta, resource_id=resource_id,
            permit_count=permit_count,
            reserved_service_quanta=reserved_service_quanta,
        ))

    def rollback_grant(
        self, *, tenant_id: str | None, flow_id: str,
        resource_id: str | None = None, permit_count: int = 1,
        reserved_service_quanta: int = 0,
    ) -> None:
        self._mutation("rollback", dict(
            tenant_id=tenant_id, flow_id=flow_id, resource_id=resource_id,
            permit_count=permit_count,
            reserved_service_quanta=reserved_service_quanta,
        ))

    def release_flow(
        self, flow_id: str, *, tenant_id: str | None,
        resource_id: str | None = None,
    ) -> None:
        self._mutation("release_flow", dict(
            flow_id=flow_id, tenant_id=tenant_id, resource_id=resource_id,
        ))

    def release_resource(
        self, *, tenant_id: str | None, resource_id: str,
    ) -> None:
        self._mutation("release_resource", dict(
            tenant_id=tenant_id, resource_id=resource_id,
        ))

    def service_changes_since(
        self, revision: int | None,
    ) -> tuple[int, frozenset[str] | None]:
        """A committed journal cut and loss-detectable flow invalidations.

        Caller may update only these flow groups when its candidates share
        one tenant/resource. Checkpoint truncation, a missed event, or a
        resource-wide release invalidates the entire disposable index.
        """
        if revision is not None and (
            type(revision) is not int or revision < 0
        ):
            raise ValueError("scheduling revision must be non-negative integer")
        with self._cut_lock:
            self._read_cut()
            current = self._applied
            if revision is None or revision > current:
                return current, None
            if revision == current:
                return current, frozenset()
            # Delta readers share the same process-owned WAL session as the
            # latest service cut. A fresh SQLite transaction is still opened:
            # replay and fairness must observe all cross-process commits, not
            # a cached service value. Avoid reconnecting for every candidate
            # head re-ranking when the durable journal advances.
            with self._readers.session() as conn:
                with sqlite_read_snapshot(conn):
                    rows = tuple(conn.execute(
                        "SELECT sequence, operation, payload "
                        "FROM unified_scheduling_events "
                        "WHERE sequence>? AND sequence<=? ORDER BY sequence",
                        (revision, current),
                    ))
            # Checkpoint pruning may destroy the suffix. Never silently
            # under-invalidate when history is missing.
            if len(rows) != current - revision:
                return current, None
            affected = set()
            for offset, (sequence, operation, payload) in enumerate(rows, 1):
                if sequence != revision + offset:
                    return current, None
                if operation == "release_resource":
                    return current, None
                fields = json.loads(payload)
                flow = fields.get("flow_id")
                if type(flow) is not str or not flow:
                    return current, None
                affected.add(flow)
            return current, frozenset(affected)

    def service_revision(self) -> int:
        """Observe the committed cross-process VTC/LAS journal generation."""
        with self._cut_lock:
            self._read_cut()
            return self._applied

    def ordering_key(
        self, candidate: SchedulingCandidate, *, now_monotonic: float,
    ) -> tuple[int | float, ...]:
        with self._cut_lock:
            self._read_cut()
            return super().ordering_key(candidate, now_monotonic=now_monotonic)

    def ordering_keys(
        self,
        candidates: tuple[SchedulingCandidate, ...],
        *,
        now_monotonic: float,
    ) -> tuple[tuple[int | float, ...], ...]:
        """Observe cross-process fairness exactly once for this candidate cut."""
        with self._cut_lock:
            self._read_cut()
            return super().ordering_keys(
                candidates, now_monotonic=now_monotonic,
            )

    def ordering_keys_at_revision(
        self, candidates: tuple[SchedulingCandidate, ...], *,
        now_monotonic: float, known_revision: int | None = None,
    ) -> tuple[int, tuple[tuple[int | float, ...], ...] | None]:
        """One fresh durable read owns both cache generation and batch ranking."""
        if known_revision is not None and (
            type(known_revision) is not int or known_revision < 0
        ):
            raise ValueError("scheduling revision must be non-negative integer")
        with self._cut_lock:
            self._read_cut()
            revision = self._applied
            if revision == known_revision:
                self._validated_now(now_monotonic)
                if type(candidates) is not tuple or any(
                    not isinstance(candidate, SchedulingCandidate) for candidate in candidates
                ):
                    raise TypeError("scheduling candidate batch must contain SchedulingCandidate values")
                return revision, None
            was_inside = getattr(self._read_scope, "inside", False)
            self._read_scope.inside = True
            try:
                return revision, self.ordering_keys(
                    candidates, now_monotonic=now_monotonic,
                )
            finally:
                self._read_scope.inside = was_inside

    def select(
        self, candidates: Iterable[SchedulingCandidate], *, now_monotonic: float,
    ) -> int:
        with self._cut_lock:
            self._read_cut()
            self._read_scope.inside = True
            try:
                return super().select(candidates, now_monotonic=now_monotonic)
            finally:
                self._read_scope.inside = False
