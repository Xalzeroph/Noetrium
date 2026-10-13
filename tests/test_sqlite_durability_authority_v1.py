from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.governance.architecture.sqlite_durability_invariants import (
    audit_sqlite_durability_invariants,
)


ROOT = Path(__file__).resolve().parents[1]


def test_sqlite_connection_mechanics_have_one_platform_authority() -> None:
    assert audit_sqlite_durability_invariants(ROOT) == []


def test_raw_sqlite_transaction_control_is_forbidden(tmp_path: Path) -> None:
    source = tmp_path / "noetrium_platform" / "rogue_transaction.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def mutate(db):\n"
        "    db.execute(\"BEGIN IMMEDIATE\")\n"
        "    db.execute(\"COMMIT\")\n"
        "    db.execute(\"ROLLBACK\")\n",
        encoding="utf-8",
    )
    findings = audit_sqlite_durability_invariants(tmp_path)
    assert [row.line for row in findings] == [2, 3, 4]
    assert all(
        row.invariant == "sqlite_durability_authority"
        for row in findings
    )


def test_reference_sqlite_transaction_control_is_forbidden(tmp_path: Path) -> None:
    source = tmp_path / "components" / "reference" / "rogue.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "import sqlite3\n"
        "def mutate(path):\n"
        "    db = sqlite3.connect(path)\n"
        "    db.execute(\"BEGIN IMMEDIATE\")\n",
        encoding="utf-8",
    )
    findings = audit_sqlite_durability_invariants(tmp_path)
    assert {row.invariant for row in findings} == {"sqlite_durability_authority"}
    assert {row.line for row in findings} == {3, 4}


def test_owned_sqlite_reader_closes_connection_on_context_exit(
    tmp_path: Path,
) -> None:
    import sqlite3

    from noetrium_platform.foundation.kernel.kernel.durability import (
        durable_sqlite_connection,
        durable_sqlite_reader,
    )

    path = tmp_path / "owned-reader.sqlite3"
    with durable_sqlite_connection(path, timeout_seconds=1.0) as db:
        db.execute("CREATE TABLE facts(value INTEGER NOT NULL)")
        db.execute("INSERT INTO facts(value) VALUES(7)")

    with durable_sqlite_reader(path, timeout_seconds=1.0) as reader:
        assert reader.execute("SELECT value FROM facts").fetchone() == (7,)
        escaped = reader

    try:
        escaped.execute("SELECT 1")
    except sqlite3.ProgrammingError as exc:
        assert "closed" in str(exc).lower()
    else:
        raise AssertionError("owned SQLite reader escaped without close")


def test_execution_permit_rollback_is_not_sqlite_rollback(tmp_path: Path) -> None:
    source = tmp_path / "noetrium_platform" / "execution_permit.py"
    source.parent.mkdir(parents=True)
    source.write_text("def abandon(lease):\n    lease.rollback()\n", encoding="utf-8")
    assert audit_sqlite_durability_invariants(tmp_path) == []


def test_explicit_sqlite_connection_rollback_is_still_rejected(tmp_path: Path) -> None:
    source = tmp_path / "noetrium_platform" / "incorrect_sqlite.py"
    source.parent.mkdir(parents=True)
    source.write_text("def abandon(conn):\n    conn.rollback()\n", encoding="utf-8")
    findings = audit_sqlite_durability_invariants(tmp_path)
    assert len(findings) == 1
    assert findings[0].invariant == "sqlite_durability_authority"
