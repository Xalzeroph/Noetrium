from pathlib import Path

from noetrium_platform.foundation.governance.architecture.lifetime_ownership_invariants import (
    audit_lifetime_ownership_invariants,
)


def test_lifetime_owner_boundaries_are_fail_closed() -> None:
    assert audit_lifetime_ownership_invariants(Path(".")) == []
