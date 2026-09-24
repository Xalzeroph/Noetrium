from __future__ import annotations

from contextlib import contextmanager
from enum import StrEnum
import math
from pathlib import Path
import sqlite3
from typing import Iterator

from noetrium_platform.foundation.kernel.kernel.retry import retry_until_deadline


class SQLiteDurabilityProfile(StrEnum):
    AUTHORITATIVE = "authoritative"
    PROJECTION = "projection"


def is_sqlite_lock_contention(exc: BaseException) -> bool:
    """Return whether SQLite reported transient lock/busy contention."""
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    code = getattr(exc, "sqlite_errorcode", None)
    if isinstance(code, bool) or not isinstance(code, int):
        return False
    base_code = code & 0xFF
    return base_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}


def _validated_timeout(timeout_seconds: float) -> float:
    timeout = float(timeout_seconds)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError(
            "SQLite connection timeout_seconds must be finite and positive"
        )
    return timeout


def open_durable_sqlite_writer(
    path: str | Path,
    *,
    timeout_seconds: float,
    profile: SQLiteDurabilityProfile = SQLiteDurabilityProfile.AUTHORITATIVE,
) -> sqlite3.Connection:
    """Open one SQLite writer under the canonical platform durability policy."""
    timeout = _validated_timeout(timeout_seconds)
    if not isinstance(profile, SQLiteDurabilityProfile):
        raise TypeError("SQLite durability profile must be typed")
    conn = sqlite3.connect(
        Path(path),
        timeout=timeout,
        isolation_level=None,
    )
    try:
        conn.execute(
            f"PRAGMA busy_timeout={max(1, int(timeout * 1000))}"
        )
        retry_until_deadline(
            lambda: conn.execute("PRAGMA journal_mode=WAL"),
            should_retry=is_sqlite_lock_contention,
            timeout_seconds=timeout,
        )
        conn.execute(
            "PRAGMA synchronous="
            + (
                "FULL"
                if profile is SQLiteDurabilityProfile.AUTHORITATIVE
                else "NORMAL"
            )
        )
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
    except BaseException:
        conn.close()
        raise


def open_durable_sqlite_reader(
    path: str | Path,
    *,
    timeout_seconds: float,
) -> sqlite3.Connection:
    """Open one read-only SQLite session over an existing durable database."""
    timeout = _validated_timeout(timeout_seconds)
    resolved = Path(path).resolve().as_posix()
    conn = sqlite3.connect(
        f"file:{resolved}?mode=ro",
        uri=True,
        timeout=timeout,
        isolation_level=None,
    )
    try:
        conn.execute(
            f"PRAGMA busy_timeout={max(1, int(timeout * 1000))}"
        )
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
    except BaseException:
        conn.close()
        raise


@contextmanager
def durable_sqlite_connection(
    path: str | Path,
    *,
    timeout_seconds: float,
    profile: SQLiteDurabilityProfile = SQLiteDurabilityProfile.AUTHORITATIVE,
) -> Iterator[sqlite3.Connection]:
    """Yield one durable writer and guarantee connection close."""
    conn = open_durable_sqlite_writer(
        path,
        timeout_seconds=timeout_seconds,
        profile=profile,
    )
    try:
        yield conn
    finally:
        conn.close()


def begin_immediate_sqlite_transaction(
    db: sqlite3.Connection,
    *,
    timeout_seconds: float,
) -> None:
    """Acquire one IMMEDIATE write transaction under canonical lock retry policy."""
    timeout = _validated_timeout(timeout_seconds)
    retry_until_deadline(
        lambda: db.execute("BEGIN IMMEDIATE"),
        should_retry=is_sqlite_lock_contention,
        timeout_seconds=timeout,
    )


@contextmanager
def sqlite_read_snapshot(
    db: sqlite3.Connection,
) -> Iterator[sqlite3.Connection]:
    """Own one explicit read snapshot under the canonical SQLite authority."""
    if db.in_transaction:
        raise RuntimeError("SQLite read snapshot requires an idle connection")
    db.execute("BEGIN")
    try:
        yield db
    finally:
        if db.in_transaction:
            db.rollback()


@contextmanager
def immediate_sqlite_transaction(
    db: sqlite3.Connection,
    *,
    timeout_seconds: float,
    label: str,
) -> Iterator[sqlite3.Connection]:
    """Own one IMMEDIATE transaction under the canonical SQLite policy."""
    if type(label) is not str or not label.strip():
        raise ValueError("SQLite transaction label must be non-empty text")
    begin_immediate_sqlite_transaction(
        db,
        timeout_seconds=timeout_seconds,
    )
    try:
        yield db
        db.commit()
    except BaseException as primary:
        rollback_sqlite_writer(
            db,
            primary,
            label=label,
        )
        raise


def abort_sqlite_writer(
    db: sqlite3.Connection,
) -> None:
    """Abort an active SQLite transaction when no primary failure exists."""
    if not db.in_transaction:
        return
    db.rollback()


def rollback_sqlite_writer(
    db: sqlite3.Connection,
    primary: BaseException,
    *,
    label: str,
) -> None:
    """Rollback without replacing the primary failure."""
    if type(label) is not str or not label.strip():
        raise ValueError("SQLite rollback label must be non-empty text")
    if not db.in_transaction:
        return
    try:
        db.rollback()
    except BaseException as rollback_exc:
        primary.add_note(
            f"{label.strip()} sqlite rollback failed: "
            f"{type(rollback_exc).__name__}"
        )


__all__ = [
    "abort_sqlite_writer",
    "begin_immediate_sqlite_transaction",
    "is_sqlite_lock_contention",
    "immediate_sqlite_transaction",
    "SQLiteDurabilityProfile",
    "durable_sqlite_connection",
    "open_durable_sqlite_reader",
    "open_durable_sqlite_writer",
    "rollback_sqlite_writer",
    "sqlite_read_snapshot",
]
