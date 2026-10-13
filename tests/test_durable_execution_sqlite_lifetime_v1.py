from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
from threading import Barrier

import pytest

from noetrium_platform.research.execution.operation.api import CommandConflict, CommandCorruption, CommandId, ExecutionCommand
from noetrium_platform.research.execution.operation.command.providers import SQLiteCommandStore
from noetrium_platform.research.execution.operation.api import OperationConflict, OperationCorruption, OperationId
from noetrium_platform.research.execution.operation.providers import SQLiteOperationStore
from noetrium_platform.research.execution.operation.runtime import OperationOwner

class TrackingConnection(sqlite3.Connection):
    tracker: dict[str, object]

    def execute(self, sql, parameters=(), /):
        normalized = sql.strip().upper()
        if self.tracker.get("fail_operation_insert") and normalized.startswith("INSERT INTO OPERATIONS"):
            raise sqlite3.OperationalError("injected operation insert failure")
        return super().execute(sql, parameters)

    def rollback(self):
        self.tracker["rollbacks"] = int(self.tracker["rollbacks"]) + 1
        return super().rollback()

    def close(self):
        self.tracker["closed"] = int(self.tracker["closed"]) + 1
        return super().close()


def _tracked_store(monkeypatch, store_type, path):
    import noetrium_platform.foundation.kernel.kernel.durability.sqlite as sqlite_runtime

    tracker = {
        "created": 0,
        "closed": 0,
        "rollbacks": 0,
        "fail_operation_insert": False,
    }

    def open_writer(
        target,
        *,
        timeout_seconds,
        profile=sqlite_runtime.SQLiteDurabilityProfile.AUTHORITATIVE,
        check_same_thread=True,
    ):
        db = sqlite3.connect(
            target,
            timeout=timeout_seconds,
            isolation_level=None,
            check_same_thread=check_same_thread,
            factory=TrackingConnection,
        )
        db.tracker = tracker
        tracker["created"] = int(tracker["created"]) + 1
        db.execute(f"PRAGMA busy_timeout={max(1, int(timeout_seconds * 1000))}")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute(
            "PRAGMA synchronous="
            + (
                "FULL"
                if profile is sqlite_runtime.SQLiteDurabilityProfile.AUTHORITATIVE
                else "NORMAL"
            )
        )
        db.execute("PRAGMA foreign_keys=ON")
        return db

    monkeypatch.setattr(sqlite_runtime, "open_durable_sqlite_writer", open_writer)
    return store_type(path), tracker


def _assert_reused_writer(tracker):
    assert tracker["created"] == 1
    assert tracker["closed"] == 0


def _command(command_id="cmd-1", command_type="environment.action"):
    return ExecutionCommand.create(
        command_id=command_id,
        command_type=command_type,
        payload_schema="action.v1",
        payload_digest="c" * 64,
        deduplication_key="request-1",
        now_unix=10.0,
        deadline_unix=30.0,
    )


def test_command_sqlite_writer_reuses_one_connection_and_rolls_back(
    tmp_path: Path,
    monkeypatch,
):
    path = tmp_path / "commands.sqlite3"
    store, tracker = _tracked_store(monkeypatch, SQLiteCommandStore, path)
    store.create_or_get(_command())
    _assert_reused_writer(tracker)
    assert store.load(CommandId("cmd-1")) is not None
    _assert_reused_writer(tracker)
    before_rollbacks = int(tracker["rollbacks"])
    with pytest.raises(CommandConflict):
        store.create_or_get(_command(command_type="different.action"))
    _assert_reused_writer(tracker)
    assert int(tracker["rollbacks"]) == before_rollbacks + 1
    with sqlite3.connect(path) as db:
        db.execute("UPDATE commands SET submitted_at=? WHERE command_id=?", ("bad", "cmd-1"))
    with pytest.raises(CommandCorruption):
        store.load(CommandId("cmd-1"))
    _assert_reused_writer(tracker)
    store.close()
    assert tracker["closed"] == 1


def test_operation_sqlite_writer_reuses_one_connection_rolls_back_and_closes(
    tmp_path: Path,
    monkeypatch,
):
    path = tmp_path / "operations.sqlite3"
    store, tracker = _tracked_store(monkeypatch, SQLiteOperationStore, path)
    owner = OperationOwner(store)
    operation, _ = owner.submit(
        CommandId("cmd-1"),
        operation_id=OperationId("op-1"),
        now_unix=10.0,
    )
    _assert_reused_writer(tracker)
    assert owner.require(operation.operation_id) == operation
    _assert_reused_writer(tracker)
    before_conflict_rollbacks = int(tracker["rollbacks"])
    with pytest.raises(OperationConflict):
        owner.submit(
            CommandId("cmd-other"),
            operation_id=operation.operation_id,
            now_unix=10.0,
        )
    _assert_reused_writer(tracker)
    assert int(tracker["rollbacks"]) == before_conflict_rollbacks + 1

    tracker["fail_operation_insert"] = True
    before_rollbacks = int(tracker["rollbacks"])
    with pytest.raises(sqlite3.OperationalError, match="injected"):
        owner.submit(
            CommandId("cmd-fail"),
            operation_id=OperationId("op-fail"),
            now_unix=10.0,
        )
    tracker["fail_operation_insert"] = False
    _assert_reused_writer(tracker)
    assert int(tracker["rollbacks"]) == before_rollbacks + 1

    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE operations SET state=? WHERE operation_id=?",
            ("invalid-state", "op-1"),
        )
    with pytest.raises(OperationCorruption):
        store.load(operation.operation_id)
    _assert_reused_writer(tracker)
    store.close()
    assert tracker["closed"] == 1


@pytest.mark.parametrize(
    ("store_type", "filename"),
    (
        (SQLiteCommandStore, "commands-first-open.sqlite3"),
        (SQLiteOperationStore, "operations-first-open.sqlite3"),
    ),
)
def test_sqlite_store_concurrent_first_open_is_race_safe(tmp_path: Path, store_type, filename: str):
    path = tmp_path / filename
    concurrency = 12
    barrier = Barrier(concurrency)

    def open_store(_index: int) -> str:
        barrier.wait(timeout=5.0)
        return store_type(path).durability

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        results = tuple(executor.map(open_store, range(concurrency)))

    assert results == ("sqlite-wal",) * concurrency
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
