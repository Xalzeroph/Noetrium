from __future__ import annotations

from contextlib import contextmanager
import math
from pathlib import Path
import sqlite3
from typing import Iterator

from noetrium_platform.foundation.kernel.kernel.retry import retry_until_deadline


@contextmanager
def durable_sqlite_connection(
    path: str | Path,
    *,
    timeout_seconds: float,
) -> Iterator[sqlite3.Connection]:
    """Open one fail-closed SQLite session with shared durability hardening.

    This primitive owns connection/session mechanics only. Callers retain
    transaction scope, schema authority, domain state machines, and writes.
    """
    timeout = float(timeout_seconds)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("SQLite connection timeout_seconds must be finite and positive")

    conn = sqlite3.connect(Path(path), timeout=timeout, isolation_level=None)
    try:
        conn.execute(f"PRAGMA busy_timeout={max(1, int(timeout * 1000))}")
        retry_until_deadline(
            lambda: conn.execute("PRAGMA journal_mode=WAL"),
            should_retry=lambda exc: (
                isinstance(exc, sqlite3.OperationalError)
                and "locked" in str(exc).lower()
            ),
            timeout_seconds=timeout,
        )
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
    finally:
        conn.close()


__all__ = ["durable_sqlite_connection"]
