from __future__ import annotations

import sqlite3
from time import monotonic

import pytest

from noetrium_platform.foundation.kernel.kernel.durability.sqlite import (
    begin_immediate_sqlite_transaction,
    open_durable_sqlite_writer,
)


def test_begin_immediate_honors_shorter_deadline_than_connection_busy_timeout(tmp_path):
    path = tmp_path / "writer.sqlite3"
    holder = open_durable_sqlite_writer(path, timeout_seconds=1.0)
    contender = open_durable_sqlite_writer(path, timeout_seconds=1.0)
    try:
        holder.execute("CREATE TABLE IF NOT EXISTS t(value INTEGER)")
        holder.execute("BEGIN IMMEDIATE")
        original_busy_ms = int(contender.execute("PRAGMA busy_timeout").fetchone()[0])

        started = monotonic()
        with pytest.raises(sqlite3.OperationalError):
            begin_immediate_sqlite_transaction(contender, timeout_seconds=0.05)
        elapsed = monotonic() - started

        assert elapsed < 0.25
        assert int(contender.execute("PRAGMA busy_timeout").fetchone()[0]) == original_busy_ms
    finally:
        if holder.in_transaction:
            holder.rollback()
        holder.close()
        contender.close()
