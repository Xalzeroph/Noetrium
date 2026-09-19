from __future__ import annotations

import inspect
import math
from pathlib import Path
import sqlite3

import pytest

from noetrium_platform.infrastructure.resources.providers import (
    SQLiteEndpointAllocationStore,
    SQLiteResourceLeaseRegistry,
)
from noetrium_platform.infrastructure.resources.providers import sqlite_connection
from noetrium_platform.infrastructure.resources.providers.sqlite_connection import durable_sqlite_connection
from noetrium_platform.infrastructure.resources.providers import sqlite_endpoint, sqlite_lease


def test_hardened_sqlite_session_applies_durable_pragmas_and_closes(tmp_path: Path) -> None:
    database = tmp_path / "shared.sqlite3"
    with durable_sqlite_connection(database, timeout_seconds=0.2) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        assert conn.execute("PRAGMA synchronous").fetchone() == (2,)
        assert conn.execute("PRAGMA foreign_keys").fetchone() == (1,)
        busy_timeout = int(conn.execute("PRAGMA busy_timeout").fetchone()[0])
        assert busy_timeout >= 200
        held = conn

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        held.execute("SELECT 1")

def test_both_durable_resource_authorities_consume_the_same_connection_primitive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed_timeouts: list[float] = []
    original = sqlite_connection.retry_until_deadline

    def observed_retry(operation, *, should_retry, timeout_seconds, interval_seconds=0.01):
        observed_timeouts.append(float(timeout_seconds))
        return original(
            operation,
            should_retry=should_retry,
            timeout_seconds=timeout_seconds,
            interval_seconds=interval_seconds,
        )

    monkeypatch.setattr(sqlite_connection, "retry_until_deadline", observed_retry)
    database = tmp_path / "authorities.sqlite3"
    SQLiteResourceLeaseRegistry(database, timeout_seconds=0.15)
    SQLiteEndpointAllocationStore(database, timeout_seconds=0.25)

    assert observed_timeouts == [0.15, 0.25]
    with sqlite3.connect(database) as conn:
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "resource_leases" in tables
    assert "endpoint_allocations" in tables

def test_connection_hardening_does_not_absorb_domain_transaction_authority() -> None:
    helper_source = inspect.getsource(sqlite_connection)
    lease_source = inspect.getsource(sqlite_lease)
    endpoint_source = inspect.getsource(sqlite_endpoint)

    assert "BEGIN IMMEDIATE" not in helper_source
    assert "ensure_resource_schema" not in helper_source
    assert "endpoint_allocations" not in helper_source
    assert "resource_leases" not in helper_source

    assert "BEGIN IMMEDIATE" in lease_source
    assert "BEGIN IMMEDIATE" in endpoint_source
    assert "PRAGMA journal_mode=WAL" not in lease_source
    assert "PRAGMA journal_mode=WAL" not in endpoint_source
    assert "durable_sqlite_connection" in lease_source
    assert "durable_sqlite_connection" in endpoint_source


@pytest.mark.parametrize("timeout_seconds", [0.0, -1.0, math.inf, -math.inf, math.nan])
def test_hardened_sqlite_session_rejects_invalid_deadlines(
    tmp_path: Path, timeout_seconds: float
) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        with durable_sqlite_connection(
            tmp_path / "invalid.sqlite3", timeout_seconds=timeout_seconds
        ):
            raise AssertionError("invalid timeout must fail before opening a session")
