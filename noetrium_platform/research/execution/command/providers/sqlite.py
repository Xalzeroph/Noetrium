from __future__ import annotations

from contextlib import closing
import sqlite3
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.retry import retry_until_deadline
from noetrium_platform.research.execution.command.api import (
    CommandConflict,
    CommandCorruption,
    CommandDeduplicationKey,
    CommandId,
    ExecutionCommand,
)


class SQLiteCommandStore:
    """Durable immutable command-intent authority backed by SQLite WAL."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @property
    def durability(self) -> str:
        return "sqlite-wal"

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._path, timeout=30.0, isolation_level=None)
        db.execute("PRAGMA busy_timeout=30000")
        db.execute("PRAGMA synchronous=FULL")
        return db

    def _initialize(self) -> None:
        retry_until_deadline(
            self._initialize_once,
            should_retry=lambda exc: isinstance(exc, sqlite3.OperationalError)
            and "locked" in str(exc).lower(),
            timeout_seconds=30.0,
        )

    def _initialize_once(self) -> None:
        with closing(self._connect()) as db, db:
            if db.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
                db.execute("PRAGMA journal_mode=WAL").fetchone()
            db.execute("""CREATE TABLE IF NOT EXISTS commands (
                command_id TEXT PRIMARY KEY,
                command_type TEXT NOT NULL,
                payload_schema TEXT NOT NULL,
                payload_digest TEXT NOT NULL,
                submitted_at REAL NOT NULL,
                deduplication_key TEXT UNIQUE,
                deadline_unix REAL
            )""")
            columns = tuple(row[1] for row in db.execute("PRAGMA table_info(commands)"))
            expected = (
                "command_id", "command_type", "payload_schema", "payload_digest",
                "submitted_at", "deduplication_key", "deadline_unix",
            )
            if columns != expected:
                raise CommandCorruption("command schema does not match current durable contract")
        return

    @staticmethod
    def _decode(row: tuple[object, ...]) -> ExecutionCommand:
        if not isinstance(row, tuple) or len(row) != 7:
            raise CommandCorruption("command row shape is invalid")
        if not all(isinstance(row[index], str) for index in (0, 1, 2, 3)):
            raise CommandCorruption("command identity/type/schema/digest columns must be text")
        if isinstance(row[4], bool) or not isinstance(row[4], (int, float)):
            raise CommandCorruption("command submitted_at must be numeric")
        if row[5] is not None and not isinstance(row[5], str):
            raise CommandCorruption("command deduplication key must be text or null")
        if row[6] is not None and (isinstance(row[6], bool) or not isinstance(row[6], (int, float))):
            raise CommandCorruption("command deadline must be numeric or null")
        try:
            return ExecutionCommand(
                CommandId(row[0]), row[1], row[2], row[3], float(row[4]),
                None if row[5] is None else CommandDeduplicationKey(row[5]),
                None if row[6] is None else float(row[6]),
            )
        except (TypeError, ValueError) as exc:
            raise CommandCorruption("command row violates typed immutable contract") from exc

    @staticmethod
    def _values(command: ExecutionCommand) -> tuple[object, ...]:
        return (
            command.command_id.value, command.command_type, command.payload_schema,
            command.payload_digest, command.submitted_at_unix,
            None if command.deduplication_key is None else command.deduplication_key.value,
            command.deadline_unix,
        )

    @staticmethod
    def _same(existing: ExecutionCommand, command: ExecutionCommand) -> bool:
        return existing == command

    def create_or_get(self, command: ExecutionCommand) -> tuple[ExecutionCommand, bool]:
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT * FROM commands WHERE command_id=?",
                    (command.command_id.value,),
                ).fetchone()
                if row is not None:
                    existing = self._decode(row)
                    if not self._same(existing, command):
                        raise CommandConflict(
                            f"command identity reused with different immutable intent: {command.command_id.value}"
                        )
                    db.execute("COMMIT")
                    return existing, False

                if command.deduplication_key is not None:
                    row = db.execute(
                        "SELECT * FROM commands WHERE deduplication_key=?",
                        (command.deduplication_key.value,),
                    ).fetchone()
                    if row is not None:
                        existing = self._decode(row)
                        raise CommandConflict(
                            "command deduplication key already belongs to immutable command "
                            f"{existing.command_id.value}"
                        )

                db.execute(
                    "INSERT INTO commands VALUES (?,?,?,?,?,?,?)",
                    self._values(command),
                )
                db.execute("COMMIT")
                return command, True
            except CommandConflict:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
            except sqlite3.IntegrityError as exc:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise CommandConflict("command identity/deduplication conflict") from exc
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise

    def load(self, command_id: CommandId) -> ExecutionCommand | None:
        with closing(self._connect()) as db, db:
            row = db.execute(
                "SELECT * FROM commands WHERE command_id=?", (command_id.value,)
            ).fetchone()
        return None if row is None else self._decode(row)

    def load_by_deduplication_key(
        self, key: CommandDeduplicationKey
    ) -> ExecutionCommand | None:
        with closing(self._connect()) as db, db:
            row = db.execute(
                "SELECT * FROM commands WHERE deduplication_key=?", (key.value,)
            ).fetchone()
        return None if row is None else self._decode(row)


__all__ = ["SQLiteCommandStore"]
