from __future__ import annotations

from pathlib import Path
import sqlite3
import time

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.foundation.kernel.kernel.durability.sqlite import (
    DurableSQLiteReaderOwner,
    DurableSQLiteWriterOwner,
    immediate_sqlite_transaction,
    sqlite_read_snapshot,
)

from ..api.budget import (
    ExecutionBudgetAuthorityPort,
    ExecutionBudgetDelta,
    ExecutionBudgetExceeded,
    ExecutionBudgetPolicy,
    ExecutionBudgetReservation,
    ExecutionBudgetReservationRequest,
    ExecutionBudgetSnapshot,
)


_FIELDS = (
    "steps",
    "turns",
    "messages",
    "model_calls",
    "tokens",
    "working_seconds",
    "cost_usd",
)


def _delta_values(value: ExecutionBudgetDelta) -> tuple[object, ...]:
    return tuple(getattr(value, name) for name in _FIELDS)


def _delta_from_row(row: tuple[object, ...]) -> ExecutionBudgetDelta:
    return ExecutionBudgetDelta(
        steps=int(row[0]),
        turns=int(row[1]),
        messages=int(row[2]),
        model_calls=int(row[3]),
        tokens=int(row[4]),
        working_seconds=float(row[5]),
        cost_usd=float(row[6]),
    )


def _add(left: ExecutionBudgetDelta, right: ExecutionBudgetDelta) -> ExecutionBudgetDelta:
    return ExecutionBudgetDelta(
        steps=left.steps + right.steps,
        turns=left.turns + right.turns,
        messages=left.messages + right.messages,
        model_calls=left.model_calls + right.model_calls,
        tokens=left.tokens + right.tokens,
        working_seconds=left.working_seconds + right.working_seconds,
        cost_usd=left.cost_usd + right.cost_usd,
    )


class SQLiteExecutionBudgetAuthority(ExecutionBudgetAuthorityPort):
    """Crash-durable per-execution budget authority.

    A scope is normally one scientific Trial/assignment lifetime. Reservations
    are idempotent by charge_id and are serialized with BEGIN IMMEDIATE, so
    concurrent participant/model children cannot each consume the full budget.
    """

    _TIMEOUT = 30.0

    def __init__(
        self,
        path: str | Path,
        *,
        resource_policy_digest: str,
        checkpoint_replay_proof_digest: str,
        exact_replay_proof_digest: str | None = None,
        cost_accounting_digest: str | None = None,
        clock_ns=time.time_ns,
    ) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.resource_policy_digest = require_sha256(
            resource_policy_digest,
            "execution budget resource policy digest",
        )
        self.checkpoint_replay_proof_digest = require_sha256(
            checkpoint_replay_proof_digest,
            "execution budget checkpoint replay proof digest",
        )
        self.exact_replay_proof_digest = (
            None
            if exact_replay_proof_digest is None
            else require_sha256(
                exact_replay_proof_digest,
                "execution budget exact replay proof digest",
            )
        )
        self.cost_accounting_digest = (
            None
            if cost_accounting_digest is None
            else require_sha256(
                cost_accounting_digest,
                "execution budget cost accounting digest",
            )
        )
        if not callable(clock_ns):
            raise TypeError("execution budget clock must be callable")
        self._clock_ns = clock_ns
        self._identity_digest = canonical_digest(
            {
                "schema": "noetrium.execution-budget-authority.v1",
                "resource_policy_digest": self.resource_policy_digest,
                "checkpoint_replay_proof_digest": (
                    self.checkpoint_replay_proof_digest
                ),
                "exact_replay_proof_digest": self.exact_replay_proof_digest,
                "cost_accounting_digest": self.cost_accounting_digest,
            }
        )
        self._writers = DurableSQLiteWriterOwner(
            self.path,
            timeout_seconds=self._TIMEOUT,
        )
        self._readers = DurableSQLiteReaderOwner(
            self.path,
            timeout_seconds=self._TIMEOUT,
        )
        # Scope policy is immutable after its one-way activation transition
        # (started_unix_ns: 0 -> timestamp). Only cache rows observed active;
        # usage/reservation state remains exclusively SQLite-authoritative.
        self._active_scope_rows: dict[str, tuple[object, ...]] = {}
        with self._writers.session() as db:
            self._ensure_schema(db)

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    @property
    def writer_connection_open_count(self) -> int:
        return self._writers.open_count

    def close(self) -> None:
        self._readers.close()
        self._writers.close()

    @staticmethod
    def _ensure_schema(db: sqlite3.Connection) -> None:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS execution_budget_scopes(
                scope_id TEXT PRIMARY KEY,
                policy_digest TEXT NOT NULL,
                budget_id TEXT NOT NULL,
                budget_digest TEXT NOT NULL,
                replay_level TEXT NOT NULL,
                started_unix_ns INTEGER NOT NULL,
                max_steps INTEGER,
                max_seconds REAL,
                max_tokens INTEGER,
                resource_budget_digest TEXT,
                max_turns INTEGER,
                max_messages INTEGER,
                max_model_calls INTEGER,
                max_working_seconds REAL,
                max_cost_usd REAL,
                admission_digest TEXT NOT NULL,
                replay_proof_digest TEXT NOT NULL,
                resource_policy_digest TEXT NOT NULL,
                cost_accounting_digest TEXT
            );
            CREATE TABLE IF NOT EXISTS execution_budget_charges(
                scope_id TEXT NOT NULL,
                charge_id TEXT NOT NULL,
                reservation_digest TEXT NOT NULL,
                state TEXT NOT NULL,
                requested_steps INTEGER NOT NULL,
                requested_turns INTEGER NOT NULL,
                requested_messages INTEGER NOT NULL,
                requested_model_calls INTEGER NOT NULL,
                requested_tokens INTEGER NOT NULL,
                requested_working_seconds REAL NOT NULL,
                requested_cost_usd REAL NOT NULL,
                actual_steps INTEGER,
                actual_turns INTEGER,
                actual_messages INTEGER,
                actual_model_calls INTEGER,
                actual_tokens INTEGER,
                actual_working_seconds REAL,
                actual_cost_usd REAL,
                PRIMARY KEY(scope_id, charge_id),
                FOREIGN KEY(scope_id)
                    REFERENCES execution_budget_scopes(scope_id)
                    ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_execution_budget_charges_scope_state
                ON execution_budget_charges(scope_id,state,charge_id);
            """
        )

    def _replay_proof(self, level: str) -> str:
        if level == "observational":
            return canonical_digest(
                {
                    "schema": "noetrium.replay-proof.v1",
                    "level": "observational",
                    "claim": "evidence-auditability-only",
                }
            )
        if level == "checkpoint":
            return self.checkpoint_replay_proof_digest
        if level == "exact":
            if self.exact_replay_proof_digest is None:
                raise ExecutionBudgetExceeded(
                    "ReplayLevel.EXACT requires an explicit owner-system exact-replay proof"
                )
            return self.exact_replay_proof_digest
        raise ValueError(f"unsupported replay level: {level!r}")

    def _admission(self, policy: ExecutionBudgetPolicy) -> tuple[str, str]:
        if (
            policy.resource_budget_digest is not None
            and policy.resource_budget_digest != self.resource_policy_digest
        ):
            raise ExecutionBudgetExceeded(
                "TrialBudget resource_budget_digest does not match the active "
                "ResearchExecutionPool resource policy"
            )
        if policy.max_cost_usd is not None and self.cost_accounting_digest is None:
            raise ExecutionBudgetExceeded(
                "TrialBudget max_cost_usd requires an exact cost-accounting authority"
            )
        replay_proof = self._replay_proof(policy.replay_level)
        admission = canonical_digest(
            {
                "schema": "noetrium.execution-budget-admission.v1",
                "policy_digest": policy.policy_digest,
                "resource_policy_digest": self.resource_policy_digest,
                "replay_proof_digest": replay_proof,
                "cost_accounting_digest": self.cost_accounting_digest,
            }
        )
        return admission, replay_proof

    def open_scope(
        self,
        policy: ExecutionBudgetPolicy,
    ) -> ExecutionBudgetSnapshot:
        if not isinstance(policy, ExecutionBudgetPolicy):
            raise TypeError("execution budget open_scope requires ExecutionBudgetPolicy")
        admission, replay_proof = self._admission(policy)
        with self._writers.session() as db:
            with immediate_sqlite_transaction(
                db,
                timeout_seconds=self._TIMEOUT,
                label="execution budget open scope",
            ):
                current = db.execute(
                    """
                    SELECT policy_digest,admission_digest
                    FROM execution_budget_scopes
                    WHERE scope_id=?
                    """,
                    (policy.scope_id,),
                ).fetchone()
                if current is None:
                    db.execute(
                        """
                        INSERT INTO execution_budget_scopes(
                            scope_id,policy_digest,budget_id,budget_digest,replay_level,
                            started_unix_ns,max_steps,max_seconds,max_tokens,
                            resource_budget_digest,max_turns,max_messages,max_model_calls,
                            max_working_seconds,max_cost_usd,admission_digest,
                            replay_proof_digest,resource_policy_digest,cost_accounting_digest
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            policy.scope_id,
                            policy.policy_digest,
                            policy.budget_id,
                            policy.budget_digest,
                            policy.replay_level,
                            0,
                            policy.max_steps,
                            policy.max_seconds,
                            policy.max_tokens,
                            policy.resource_budget_digest,
                            policy.max_turns,
                            policy.max_messages,
                            policy.max_model_calls,
                            policy.max_working_seconds,
                            policy.max_cost_usd,
                            admission,
                            replay_proof,
                            self.resource_policy_digest,
                            self.cost_accounting_digest,
                        ),
                    )
                elif tuple(current) != (policy.policy_digest, admission):
                    raise RuntimeError(
                        "execution budget scope already exists with different scientific policy"
                    )
        return self.snapshot(policy.scope_id)

    def _scope_policy_row(
        self,
        db: sqlite3.Connection,
        scope_id: str,
    ) -> tuple[object, ...]:
        cached = self._active_scope_rows.get(scope_id)
        if cached is not None:
            return cached
        row = db.execute(
            """
            SELECT
                policy_digest,budget_id,budget_digest,replay_level,started_unix_ns,
                max_steps,max_seconds,max_tokens,resource_budget_digest,max_turns,
                max_messages,max_model_calls,max_working_seconds,max_cost_usd,
                admission_digest,replay_proof_digest,resource_policy_digest,
                cost_accounting_digest
            FROM execution_budget_scopes
            WHERE scope_id=?
            """,
            (scope_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown execution budget scope: {scope_id}")
        result = tuple(row)
        if int(result[4]) > 0:
            # The active row is immutable for the rest of this authority's
            # lifetime. Benign concurrent misses may publish the same value.
            existing = self._active_scope_rows.setdefault(scope_id, result)
            if existing != result:
                raise RuntimeError("active execution budget scope identity drifted")
            return existing
        return result

    @staticmethod
    def _usage_and_reserved(
        db: sqlite3.Connection,
        scope_id: str,
    ) -> tuple[ExecutionBudgetDelta, ExecutionBudgetDelta]:
        usage_columns = ",".join(
            f"COALESCE(SUM(CASE WHEN state='committed' "
            f"THEN actual_{name} ELSE 0 END),0)"
            for name in _FIELDS
        )
        reserved_columns = ",".join(
            f"COALESCE(SUM(CASE WHEN state='reserved' "
            f"THEN requested_{name} ELSE 0 END),0)"
            for name in _FIELDS
        )
        row = db.execute(
            f"""
            SELECT {usage_columns},{reserved_columns}
            FROM execution_budget_charges
            WHERE scope_id=? AND state IN ('committed','reserved')
            """,
            (scope_id,),
        ).fetchone()
        assert row is not None
        split = len(_FIELDS)
        return (
            _delta_from_row(tuple(row[:split])),
            _delta_from_row(tuple(row[split:])),
        )

    @staticmethod
    def _limits(scope: tuple[object, ...]) -> dict[str, float | int | None]:
        return {
            "steps": scope[5],
            "tokens": scope[7],
            "turns": scope[9],
            "messages": scope[10],
            "model_calls": scope[11],
            "working_seconds": None,
            "cost_usd": scope[13],
        }

    def _time_violation(self, scope: tuple[object, ...]) -> str | None:
        started = int(scope[4])
        if started <= 0:
            return None
        elapsed = max(
            0.0,
            (int(self._clock_ns()) - started) / 1_000_000_000,
        )
        limits = (
            ("max_seconds", scope[6]),
            ("max_working_seconds", scope[12]),
        )
        for name, limit in limits:
            if limit is not None and elapsed > float(limit):
                return (
                    f"{name}:elapsed={elapsed:.6f}:limit={float(limit):.6f}"
                )
        return None

    @classmethod
    def _violations(
        cls,
        scope: tuple[object, ...],
        total: ExecutionBudgetDelta,
    ) -> tuple[str, ...]:
        rows: list[str] = []
        limits = cls._limits(scope)
        for name, limit in limits.items():
            if limit is None:
                continue
            value = getattr(total, name)
            if float(value) > float(limit):
                rows.append(f"{name}:used={value}:limit={limit}")
        return tuple(rows)

    @staticmethod
    def _snapshot_from_rows(
        scope_id: str,
        scope: tuple[object, ...],
        usage: ExecutionBudgetDelta,
        reserved: ExecutionBudgetDelta,
    ) -> ExecutionBudgetSnapshot:
        return ExecutionBudgetSnapshot(
            scope_id=scope_id,
            policy_digest=str(scope[0]),
            usage=usage,
            reserved=reserved,
            started_unix_ns=int(scope[4]),
            admission_digest=str(scope[14]),
            replay_proof_digest=str(scope[15]),
            resource_policy_digest=str(scope[16]),
            cost_accounting_digest=(
                None if scope[17] is None else str(scope[17])
            ),
        )

    def _snapshot_from_db(
        self,
        db: sqlite3.Connection,
        scope_id: str,
    ) -> ExecutionBudgetSnapshot:
        scope = self._scope_policy_row(db, scope_id)
        usage, reserved = self._usage_and_reserved(db, scope_id)
        return self._snapshot_from_rows(scope_id, scope, usage, reserved)

    def snapshot(self, scope_id: str) -> ExecutionBudgetSnapshot:
        if type(scope_id) is not str or not scope_id.strip():
            raise ValueError("execution budget scope_id is required")
        with self._readers.session() as db, sqlite_read_snapshot(db):
            return self._snapshot_from_db(db, scope_id)

    def activate_scope(self, scope_id: str) -> ExecutionBudgetSnapshot:
        if type(scope_id) is not str or not scope_id.strip():
            raise ValueError("execution budget scope_id is required")
        now = int(self._clock_ns())
        if now <= 0:
            raise RuntimeError("execution budget clock returned invalid time")
        with self._writers.session() as db:
            with immediate_sqlite_transaction(
                db,
                timeout_seconds=self._TIMEOUT,
                label="execution budget activate scope",
            ):
                scope = self._scope_policy_row(db, scope_id)
                started = int(scope[4])
                if started == 0:
                    db.execute(
                        "UPDATE execution_budget_scopes SET started_unix_ns=? "
                        "WHERE scope_id=? AND started_unix_ns=0",
                        (now, scope_id),
                    )
                elif started < 0:
                    raise RuntimeError(
                        "execution budget scope has invalid activation timestamp"
                    )
                return self._snapshot_from_db(db, scope_id)

    def require_active(self, scope_id: str) -> ExecutionBudgetSnapshot:
        with self._readers.session() as db, sqlite_read_snapshot(db):
            scope = self._scope_policy_row(db, scope_id)
            if int(scope[4]) <= 0:
                raise ExecutionBudgetExceeded(
                    "TrialBudget scientific time has not been activated"
                )
            violation = self._time_violation(scope)
            if violation is not None:
                raise ExecutionBudgetExceeded(
                    "TrialBudget exhausted: " + violation
                )
            usage, reserved = self._usage_and_reserved(db, scope_id)
            violations = self._violations(scope, _add(usage, reserved))
            if violations:
                raise ExecutionBudgetExceeded(
                    "TrialBudget exhausted: " + ", ".join(violations)
                )
            return self._snapshot_from_rows(
                scope_id,
                scope,
                usage,
                reserved,
            )

    def remaining_seconds(self, scope_id: str) -> float | None:
        if type(scope_id) is not str or not scope_id.strip():
            raise ValueError("execution budget scope_id is required")
        scope = self._active_scope_rows.get(scope_id)
        if scope is None:
            with self._readers.session() as db, sqlite_read_snapshot(db):
                scope = self._scope_policy_row(db, scope_id)
        started = int(scope[4])
        elapsed = (
            0.0
            if started <= 0
            else max(
                0.0,
                (int(self._clock_ns()) - started) / 1_000_000_000,
            )
        )
        limits = tuple(
            float(limit)
            for limit in (scope[6], scope[12])
            if limit is not None
        )
        if not limits:
            return None
        return max(0.0, min(limits) - elapsed)

    def reserve(
        self,
        scope_id: str,
        charge_id: str,
        requested: ExecutionBudgetDelta,
    ) -> ExecutionBudgetReservation:
        return self.reserve_batch(
            scope_id,
            (ExecutionBudgetReservationRequest(charge_id, requested),),
        )[0]

    def reserve_batch(
        self,
        scope_id: str,
        requests: tuple[ExecutionBudgetReservationRequest, ...],
    ) -> tuple[ExecutionBudgetReservation, ...]:
        if type(scope_id) is not str or not scope_id.strip():
            raise ValueError("execution budget scope_id is required")
        if type(requests) is not tuple or not requests:
            raise ValueError(
                "execution budget reservation batch requires non-empty tuple"
            )
        if any(
            not isinstance(item, ExecutionBudgetReservationRequest)
            for item in requests
        ):
            raise TypeError(
                "execution budget reservation batch requires typed requests"
            )
        charge_ids = tuple(item.charge_id for item in requests)
        if len(set(charge_ids)) != len(charge_ids):
            raise ValueError(
                "execution budget reservation batch charge_ids must be unique"
            )
        reservation_digests = tuple(
            canonical_digest(
                {
                    "schema": "noetrium.execution-budget-reservation.v1",
                    "scope_id": scope_id,
                    "charge_id": item.charge_id,
                    "requested": item.requested,
                }
            )
            for item in requests
        )

        with self._writers.session() as db:
            with immediate_sqlite_transaction(
                db,
                timeout_seconds=self._TIMEOUT,
                label="execution budget reserve batch",
            ):
                scope = self._scope_policy_row(db, scope_id)
                if int(scope[4]) <= 0:
                    raise ExecutionBudgetExceeded(
                        "TrialBudget scientific time has not been activated"
                    )
                time_violation = self._time_violation(scope)
                if time_violation is not None:
                    raise ExecutionBudgetExceeded(
                        "TrialBudget exhausted: " + time_violation
                    )

                existing_by_id: dict[str, tuple[object, ...]] = {}
                for offset in range(0, len(charge_ids), 500):
                    chunk = charge_ids[offset : offset + 500]
                    placeholders = ",".join("?" for _ in chunk)
                    rows = db.execute(
                        """
                        SELECT charge_id,reservation_digest,state,
                               requested_steps,requested_turns,
                               requested_messages,requested_model_calls,
                               requested_tokens,requested_working_seconds,
                               requested_cost_usd
                        FROM execution_budget_charges
                        WHERE scope_id=?
                          AND charge_id IN ("""
                        + placeholders
                        + ")",
                        (scope_id, *chunk),
                    ).fetchall()
                    for row in rows:
                        existing_by_id[str(row[0])] = tuple(row[1:])

                existing_rows: list[
                    tuple[str, ExecutionBudgetDelta] | None
                ] = []
                additional = ExecutionBudgetDelta()
                for item, reservation_digest in zip(
                    requests, reservation_digests, strict=True
                ):
                    row = existing_by_id.get(item.charge_id)
                    if row is None:
                        existing_rows.append(None)
                        additional = _add(additional, item.requested)
                        continue
                    if str(row[0]) != reservation_digest:
                        raise RuntimeError(
                            "execution budget charge_id reused with "
                            "different reservation"
                        )
                    state = str(row[1])
                    requested_existing = _delta_from_row(tuple(row[2:]))
                    if requested_existing != item.requested:
                        raise RuntimeError(
                            "execution budget reservation payload drifted"
                        )
                    if state == "aborted":
                        additional = _add(additional, requested_existing)
                    elif state not in {"reserved", "committed"}:
                        raise RuntimeError(
                            "execution budget charge has unknown state: "
                            + state
                        )
                    existing_rows.append((state, requested_existing))

                usage, reserved = self._usage_and_reserved(db, scope_id)
                projected = _add(_add(usage, reserved), additional)
                violations = self._violations(scope, projected)
                if violations:
                    raise ExecutionBudgetExceeded(
                        "TrialBudget reservation rejected: "
                        + ", ".join(violations)
                    )

                insert_rows: list[tuple[object, ...]] = []
                reactivate_rows: list[tuple[str, str]] = []
                reservations: list[ExecutionBudgetReservation] = []
                for item, reservation_digest, existing in zip(
                    requests,
                    reservation_digests,
                    existing_rows,
                    strict=True,
                ):
                    if existing is None:
                        insert_rows.append(
                            (
                                scope_id,
                                item.charge_id,
                                reservation_digest,
                                "reserved",
                                *_delta_values(item.requested),
                            )
                        )
                    elif existing[0] == "aborted":
                        reactivate_rows.append((scope_id, item.charge_id))
                    reservations.append(
                        ExecutionBudgetReservation(
                            scope_id,
                            item.charge_id,
                            item.requested,
                            reservation_digest,
                        )
                    )

                if insert_rows:
                    db.executemany(
                        """
                        INSERT INTO execution_budget_charges(
                            scope_id,charge_id,reservation_digest,state,
                            requested_steps,requested_turns,
                            requested_messages,requested_model_calls,
                            requested_tokens,requested_working_seconds,
                            requested_cost_usd
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        insert_rows,
                    )
                if reactivate_rows:
                    db.executemany(
                        """
                        UPDATE execution_budget_charges
                        SET state='reserved',
                            actual_steps=NULL,actual_turns=NULL,
                            actual_messages=NULL,
                            actual_model_calls=NULL,actual_tokens=NULL,
                            actual_working_seconds=NULL,
                            actual_cost_usd=NULL
                        WHERE scope_id=? AND charge_id=?
                        """,
                        reactivate_rows,
                    )
        return tuple(reservations)

    def commit(
        self,
        reservation: ExecutionBudgetReservation,
        actual: ExecutionBudgetDelta,
    ) -> tuple[ExecutionBudgetSnapshot, tuple[str, ...]]:
        if not isinstance(reservation, ExecutionBudgetReservation):
            raise TypeError("execution budget commit requires reservation")
        if not isinstance(actual, ExecutionBudgetDelta):
            raise TypeError("execution budget commit requires typed delta")
        with self._writers.session() as db:
            with immediate_sqlite_transaction(
                db,
                timeout_seconds=self._TIMEOUT,
                label="execution budget commit",
            ):
                scope = self._scope_policy_row(db, reservation.scope_id)
                row = db.execute(
                    """
                    SELECT reservation_digest,state,
                           actual_steps,actual_turns,actual_messages,
                           actual_model_calls,actual_tokens,
                           actual_working_seconds,actual_cost_usd
                    FROM execution_budget_charges
                    WHERE scope_id=? AND charge_id=?
                    """,
                    (reservation.scope_id, reservation.charge_id),
                ).fetchone()
                if row is None:
                    raise KeyError(
                        "execution budget reservation disappeared before commit"
                    )
                if str(row[0]) != reservation.reservation_digest:
                    raise RuntimeError("execution budget reservation identity drifted")
                state = str(row[1])
                if state == "committed":
                    existing = _delta_from_row(tuple(row[2:]))
                    if existing != actual:
                        raise RuntimeError(
                            "execution budget charge replayed with different actual usage"
                        )
                    usage, reserved = self._usage_and_reserved(
                        db, reservation.scope_id
                    )
                    return self._snapshot_from_rows(
                        reservation.scope_id,
                        scope,
                        usage,
                        reserved,
                    ), ()
                if state == "aborted":
                    raise RuntimeError(
                        "execution budget aborted reservation cannot be committed"
                    )
                if state != "reserved":
                    raise RuntimeError(
                        "execution budget charge has unknown state: " + state
                    )
                db.execute(
                    """
                    UPDATE execution_budget_charges
                    SET state='committed',
                        actual_steps=?,actual_turns=?,actual_messages=?,
                        actual_model_calls=?,actual_tokens=?,
                        actual_working_seconds=?,actual_cost_usd=?
                    WHERE scope_id=? AND charge_id=?
                    """,
                    (
                        *_delta_values(actual),
                        reservation.scope_id,
                        reservation.charge_id,
                    ),
                )
                usage, reserved = self._usage_and_reserved(
                    db, reservation.scope_id
                )
                violations = list(self._violations(scope, _add(usage, reserved)))
                time_violation = self._time_violation(scope)
                if time_violation is not None:
                    violations.append(time_violation)
                snapshot = self._snapshot_from_rows(
                    reservation.scope_id,
                    scope,
                    usage,
                    reserved,
                )
        return snapshot, tuple(violations)

    def abort(
        self,
        reservation: ExecutionBudgetReservation,
    ) -> ExecutionBudgetSnapshot:
        if not isinstance(reservation, ExecutionBudgetReservation):
            raise TypeError("execution budget abort requires reservation")
        with self._writers.session() as db:
            with immediate_sqlite_transaction(
                db,
                timeout_seconds=self._TIMEOUT,
                label="execution budget abort",
            ):
                scope = self._scope_policy_row(db, reservation.scope_id)
                row = db.execute(
                    """
                    SELECT reservation_digest,state
                    FROM execution_budget_charges
                    WHERE scope_id=? AND charge_id=?
                    """,
                    (reservation.scope_id, reservation.charge_id),
                ).fetchone()
                if row is None:
                    raise KeyError(
                        "execution budget reservation disappeared before abort"
                    )
                if str(row[0]) != reservation.reservation_digest:
                    raise RuntimeError(
                        "execution budget reservation identity drifted"
                    )
                state = str(row[1])
                if state == "aborted":
                    usage, reserved = self._usage_and_reserved(
                        db, reservation.scope_id
                    )
                    return self._snapshot_from_rows(
                        reservation.scope_id,
                        scope,
                        usage,
                        reserved,
                    )
                if state == "committed":
                    raise RuntimeError(
                        "execution budget committed reservation cannot be aborted"
                    )
                if state != "reserved":
                    raise RuntimeError(
                        "execution budget charge has unknown state: " + state
                    )
                db.execute(
                    """
                    UPDATE execution_budget_charges
                    SET state='aborted'
                    WHERE scope_id=? AND charge_id=?
                    """,
                    (reservation.scope_id, reservation.charge_id),
                )
                usage, reserved = self._usage_and_reserved(
                    db, reservation.scope_id
                )
                return self._snapshot_from_rows(
                    reservation.scope_id,
                    scope,
                    usage,
                    reserved,
                )

    def consume(
        self,
        scope_id: str,
        charge_id: str,
        actual: ExecutionBudgetDelta,
    ) -> ExecutionBudgetSnapshot:
        reservation = self.reserve(scope_id, charge_id, actual)
        snapshot, violations = self.commit(reservation, actual)
        if violations:
            raise ExecutionBudgetExceeded(
                "TrialBudget consumption exceeded limit: " + ", ".join(violations)
            )
        return snapshot


__all__ = ["SQLiteExecutionBudgetAuthority"]
