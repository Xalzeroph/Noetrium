from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.governance.architecture import (
    sqlite_durability_invariants as sqlite_invariants,
)
from noetrium_platform.foundation.governance.architecture.sqlite_durability_invariants import (
    audit_sqlite_durability_invariants,
)


ROOT = Path(__file__).resolve().parents[1]


def test_sqlite_connection_mechanics_have_one_platform_authority() -> None:
    assert audit_sqlite_durability_invariants(ROOT) == []


def test_raw_sqlite_transaction_control_is_forbidden(tmp_path: Path) -> None:
    source = tmp_path / "raw_sqlite_transaction.py"
    source.write_text(
        "def mutate(db):\n"
        "    db.execute(\"BEGIN IMMEDIATE\")\n"
        "    db.execute(\"COMMIT\")\n"
        "    db.execute(\"ROLLBACK\")\n",
        encoding="utf-8",
    )
    primitives = tuple(
        primitive
        for _line, primitive
        in sqlite_invariants._sqlite_session_policy_calls(source)
    )
    assert primitives == ("BEGIN IMMEDIATE", "COMMIT", "ROLLBACK")
