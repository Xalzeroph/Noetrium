from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.sqlite import (
    DurableSQLiteWriterOwner,
    immediate_sqlite_transaction,
)
from noetrium_platform.research.execution.operation.command.api import CommandId
from noetrium_platform.research.execution.operation.api import (
    EffectId,
    OperationConflict,
    OperationCorruption,
    OperationEffectCertainty,
    OperationEffectProfile,
    OperationFailure,
    OperationFailureKind,
    OperationId,
    OperationSnapshot,
    OperationState,
    revise_operation,
    transition_operation,
)


class SQLiteOperationStore:
    """Durable operation lifecycle state; command intent remains a foreign authority."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._connections = DurableSQLiteWriterOwner(
            self._path,
            timeout_seconds=30.0,
        )
        self._initialize()

    @property
    def durability(self) -> str:
        return "sqlite-wal"

    @property
    def connection_open_count(self) -> int:
        return self._connections.open_count

    def close(self) -> None:
        self._connections.close()

    def _initialize(self) -> None:
        self._initialize_once()

    def _initialize_once(self) -> None:
        with self._connections.session() as db:
            with immediate_sqlite_transaction(
                db,
                timeout_seconds=30.0,
                label="operation schema",
            ):
                db.execute(
                    """CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY,
                    command_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    parent_operation_id TEXT,
                    effect_id TEXT,
                    effect_request_id TEXT,
                    effect_request_digest TEXT,
                    effect_profile TEXT NOT NULL,
                    effect_certainty TEXT NOT NULL,
                    result_digest TEXT,
                    failure_kind TEXT,
                    failure_code TEXT,
                    failure_message TEXT,
                    failure_retryable INTEGER,
                    failure_reconciliation_required INTEGER,
                    failure_id TEXT,
                    cancellation_requested INTEGER NOT NULL,
                    cancellation_reason TEXT)"""
                )
                columns = tuple(
                    row[1]
                    for row in db.execute("PRAGMA table_info(operations)")
                )
                expected = (
                    "operation_id",
                    "command_id",
                    "state",
                    "version",
                    "created_at",
                    "updated_at",
                    "parent_operation_id",
                    "effect_id",
                    "effect_request_id",
                    "effect_request_digest",
                    "effect_profile",
                    "effect_certainty",
                    "result_digest",
                    "failure_kind",
                    "failure_code",
                    "failure_message",
                    "failure_retryable",
                    "failure_reconciliation_required",
                    "failure_id",
                    "cancellation_requested",
                    "cancellation_reason",
                )
                if columns != expected:
                    raise OperationCorruption(
                        "operation schema does not match current durable contract"
                    )
        return

    @staticmethod
    def _from_row(row: tuple[object, ...]) -> OperationSnapshot:
        if not isinstance(row, tuple) or len(row) != 21:
            raise OperationCorruption("operation row shape is invalid")
        if not all(isinstance(row[index], str) for index in (0, 1, 2, 10, 11)):
            raise OperationCorruption("operation identity/state/effect columns must be text")
        if isinstance(row[3], bool) or not isinstance(row[3], int):
            raise OperationCorruption("operation version must be integer")
        for index, field in ((4, "created_at"), (5, "updated_at")):
            if isinstance(row[index], bool) or not isinstance(row[index], (int, float)):
                raise OperationCorruption(f"operation {field} must be numeric")
        nullable_text = ((6, "parent_operation_id"), (7, "effect_id"), (8, "effect_request_id"),
                         (9, "effect_request_digest"), (12, "result_digest"),
                         (18, "failure_id"), (20, "cancellation_reason"))
        for index, field in nullable_text:
            if row[index] is not None and not isinstance(row[index], str):
                raise OperationCorruption(f"operation {field} must be text or null")
        if row[19] not in (0, 1):
            raise OperationCorruption("operation cancellation_requested must be 0 or 1")
        failure_columns = row[13:19]
        if row[13] is None:
            if any(value is not None for value in failure_columns):
                raise OperationCorruption("operation failure columns must be all null when failure_kind is null")
            failure = None
        else:
            if not all(isinstance(row[index], str) for index in (13, 14, 15)):
                raise OperationCorruption("operation failure kind/code/message must be text")
            if row[16] not in (0, 1) or row[17] not in (0, 1):
                raise OperationCorruption("operation failure booleans must be 0 or 1")
            try:
                failure = OperationFailure(
                    OperationFailureKind(row[13]),
                    row[14],
                    row[15],
                    bool(row[16]),
                    bool(row[17]),
                    None if row[18] is None else row[18],
                )
            except (TypeError, ValueError) as exc:
                raise OperationCorruption("operation failure columns violate typed contract") from exc
        try:
            return OperationSnapshot(
                OperationId(row[0]), CommandId(row[1]), OperationState(row[2]), row[3], float(row[4]), float(row[5]),
                None if row[6] is None else OperationId(row[6]),
                None if row[7] is None else EffectId(row[7]),
                OperationEffectProfile(row[10]), OperationEffectCertainty(row[11]), row[12], failure,
                bool(row[19]), row[20],
                effect_request_id=row[8], effect_request_digest=row[9],
            )
        except (TypeError, ValueError) as exc:
            raise OperationCorruption("operation row violates typed lifecycle contract") from exc

    @staticmethod
    def _row_values(snapshot: OperationSnapshot) -> tuple[object, ...]:
        failure = snapshot.failure
        return (
            snapshot.operation_id.value,
            snapshot.command_id.value,
            snapshot.state.value,
            snapshot.version,
            snapshot.created_at_unix,
            snapshot.updated_at_unix,
            (
                None
                if snapshot.parent_operation_id is None
                else snapshot.parent_operation_id.value
            ),
            None if snapshot.effect_id is None else snapshot.effect_id.value,
            snapshot.effect_request_id,
            snapshot.effect_request_digest,
            snapshot.effect_profile.value,
            snapshot.effect_certainty.value,
            snapshot.result_digest,
            None if failure is None else failure.kind.value,
            None if failure is None else failure.code,
            None if failure is None else failure.message,
            None if failure is None else int(failure.retryable),
            None if failure is None else int(failure.reconciliation_required),
            None if failure is None else failure.failure_id,
            int(snapshot.cancellation_requested),
            snapshot.cancellation_reason,
        )

    @staticmethod
    def _immutable_identity(snapshot: OperationSnapshot) -> tuple[object, ...]:
        return (
            snapshot.command_id,
            snapshot.parent_operation_id,
            snapshot.effect_id,
            snapshot.effect_request_id,
            snapshot.effect_request_digest,
            snapshot.effect_profile,
        )

    def load(self, operation_id: OperationId) -> OperationSnapshot | None:
        with self._connections.session() as db:
            row = db.execute(
                "SELECT * FROM operations WHERE operation_id=?",
                (operation_id.value,),
            ).fetchone()
        return None if row is None else self._from_row(row)

    def create_or_get(
        self,
        snapshot: OperationSnapshot,
    ) -> tuple[OperationSnapshot, bool]:
        if snapshot.state is not OperationState.CREATED or snapshot.version != 0:
            raise ValueError("new durable operation must start at CREATED version 0")
        with self._connections.session() as db:
            with immediate_sqlite_transaction(
                db,
                timeout_seconds=30.0,
                label="operation create",
            ):
                row = db.execute(
                    "SELECT * FROM operations WHERE operation_id=?",
                    (snapshot.operation_id.value,),
                ).fetchone()
                if row is not None:
                    existing = self._from_row(row)
                    if self._immutable_identity(existing) != self._immutable_identity(
                        snapshot
                    ):
                        raise OperationConflict(
                            "operation identity reused with different immutable "
                            f"contract: {snapshot.operation_id.value}"
                        )
                    return existing, False
                db.execute(
                    "INSERT INTO operations VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        snapshot.operation_id.value,
                        snapshot.command_id.value,
                        snapshot.state.value,
                        snapshot.version,
                        snapshot.created_at_unix,
                        snapshot.updated_at_unix,
                        (
                            None
                            if snapshot.parent_operation_id is None
                            else snapshot.parent_operation_id.value
                        ),
                        (
                            None
                            if snapshot.effect_id is None
                            else snapshot.effect_id.value
                        ),
                        snapshot.effect_request_id,
                        snapshot.effect_request_digest,
                        snapshot.effect_profile.value,
                        snapshot.effect_certainty.value,
                        snapshot.result_digest,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        int(snapshot.cancellation_requested),
                        snapshot.cancellation_reason,
                    ),
                )
        return snapshot, True

    @staticmethod
    def _mutable_update_values(snapshot: OperationSnapshot) -> tuple[object, ...]:
        failure = snapshot.failure
        return (
            snapshot.state.value,
            snapshot.version,
            snapshot.updated_at_unix,
            snapshot.effect_certainty.value,
            snapshot.result_digest,
            None if failure is None else failure.kind.value,
            None if failure is None else failure.code,
            None if failure is None else failure.message,
            None if failure is None else int(failure.retryable),
            None if failure is None else int(failure.reconciliation_required),
            None if failure is None else failure.failure_id,
            int(snapshot.cancellation_requested),
            snapshot.cancellation_reason,
            snapshot.operation_id.value,
        )

    @classmethod
    def _validate_successor(
        cls, current: OperationSnapshot, expected_version: int, snapshot: OperationSnapshot
    ) -> None:
        if current.version != expected_version or snapshot.version != expected_version + 1:
            raise OperationConflict(f"operation version conflict: {snapshot.operation_id.value}")
        if cls._immutable_identity(current) != cls._immutable_identity(snapshot):
            raise OperationConflict(
                f"operation immutable identity changed during CAS: {snapshot.operation_id.value}"
            )
        if current.created_at_unix != snapshot.created_at_unix:
            raise OperationConflict(
                f"operation creation timestamp changed during CAS: {snapshot.operation_id.value}"
            )
        evidence_fields = (
            "effect_certainty", "result_digest", "failure",
            "cancellation_requested", "cancellation_reason",
        )
        try:
            if snapshot.state is current.state:
                candidate = revise_operation(
                    current,
                    now_unix=snapshot.updated_at_unix,
                    cancellation_requested=snapshot.cancellation_requested,
                    cancellation_reason=snapshot.cancellation_reason,
                )
            else:
                changes = {
                    field: getattr(snapshot, field)
                    for field in evidence_fields
                    if getattr(snapshot, field) != getattr(current, field)
                }
                candidate = transition_operation(
                    current, snapshot.state, now_unix=snapshot.updated_at_unix, **changes
                )
        except (TypeError, ValueError, RuntimeError) as exc:
            raise OperationConflict(
                f"operation CAS successor violates lifecycle authority: {snapshot.operation_id.value}"
            ) from exc
        if candidate != snapshot:
            raise OperationConflict(
                f"operation CAS successor differs from lifecycle authority: {snapshot.operation_id.value}"
            )

    def compare_and_swap(
        self,
        current: OperationSnapshot,
        snapshot: OperationSnapshot,
    ) -> OperationSnapshot:
        if not isinstance(current, OperationSnapshot):
            raise TypeError("operation CAS current must be OperationSnapshot")
        if not isinstance(snapshot, OperationSnapshot):
            raise TypeError("operation CAS successor must be OperationSnapshot")
        self._validate_successor(current, current.version, snapshot)

        # Exact-row CAS: the normal path needs no preliminary SELECT. Every
        # durable field is fenced so out-of-band drift with an unchanged
        # version cannot be silently overwritten.
        where = (
            "operation_id IS ? AND command_id IS ? AND state IS ? AND "
            "version IS ? AND created_at IS ? AND updated_at IS ? AND "
            "parent_operation_id IS ? AND effect_id IS ? AND "
            "effect_request_id IS ? AND effect_request_digest IS ? AND "
            "effect_profile IS ? AND effect_certainty IS ? AND "
            "result_digest IS ? AND failure_kind IS ? AND failure_code IS ? "
            "AND failure_message IS ? AND failure_retryable IS ? AND "
            "failure_reconciliation_required IS ? AND failure_id IS ? AND "
            "cancellation_requested IS ? AND cancellation_reason IS ?"
        )
        with self._connections.session() as db:
            cursor = db.execute(
                (
                    "UPDATE operations SET "
                    "state=?,version=?,updated_at=?,effect_certainty=?,"
                    "result_digest=?,failure_kind=?,failure_code=?,"
                    "failure_message=?,failure_retryable=?,"
                    "failure_reconciliation_required=?,failure_id=?,"
                    "cancellation_requested=?,cancellation_reason=? WHERE "
                    + where
                ),
                self._mutable_update_values(snapshot)[:-1]
                + self._row_values(current),
            )
            if cursor.rowcount == 1:
                return snapshot

            # Conflict/corruption is exceptional; read only on this path so
            # diagnostics remain fail-closed without taxing every transition.
            row = db.execute(
                "SELECT * FROM operations WHERE operation_id=?",
                (snapshot.operation_id.value,),
            ).fetchone()
            if row is None:
                raise OperationConflict(
                    f"operation version conflict: {snapshot.operation_id.value}"
                )
            observed = self._from_row(row)
            raise OperationConflict(
                "operation CAS base snapshot no longer matches durable truth: "
                f"{observed.operation_id.value}@{observed.version}"
            )



__all__ = ["SQLiteOperationStore"]
