from __future__ import annotations

from pathlib import Path
import sqlite3


def connect_artifact_writer(path: Path, *, timeout_seconds: float) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=timeout_seconds, isolation_level=None)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute(f"PRAGMA busy_timeout={int(timeout_seconds * 1000)}")
    return db


def connect_artifact_reader(path: Path, *, timeout_seconds: float) -> sqlite3.Connection:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    db = sqlite3.connect(uri, uri=True, timeout=timeout_seconds, isolation_level=None)
    db.execute("PRAGMA query_only=ON")
    db.execute(f"PRAGMA busy_timeout={int(timeout_seconds * 1000)}")
    return db


def rollback_artifact_writer(db: sqlite3.Connection, primary: BaseException) -> None:
    """Rollback an active Artifact transaction without replacing its primary failure."""

    if not db.in_transaction:
        return
    try:
        db.rollback()
    except BaseException as rollback_exc:
        primary.add_note(
            "artifact sqlite rollback failed: "
            f"{type(rollback_exc).__name__}"
        )


__all__ = ["connect_artifact_reader", "connect_artifact_writer", "rollback_artifact_writer"]
