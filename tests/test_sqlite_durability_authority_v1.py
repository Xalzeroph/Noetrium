from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.governance.architecture.sqlite_durability_invariants import (
    audit_sqlite_durability_invariants,
)


ROOT = Path(__file__).resolve().parents[1]


def test_sqlite_connection_mechanics_have_one_platform_authority() -> None:
    assert audit_sqlite_durability_invariants(ROOT) == []
