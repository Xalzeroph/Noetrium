from __future__ import annotations

import pytest

from noetrium_platform.composition.platform_meta import build_platform_meta
from noetrium_platform.infrastructure.reliability.recovery.api import RecoveryLeaseBusy
from noetrium_platform.composition.reliability_resources import (
    compose_resource_recovery_lease,
)
from noetrium_platform.infrastructure.reliability.recovery.execution.composition import (
    compose_file_locked_recovery_execution,
)


def test_recovery_execution_uses_platform_resource_authority_and_local_fence(
    tmp_path,
) -> None:
    meta = build_platform_meta(tmp_path / "meta")
    lease = compose_resource_recovery_lease(
        meta.resource_ownership,
        meta.resource_leases,
        evidence_refs=("test-shared-platform-meta",),
    )
    first = compose_file_locked_recovery_execution(
        lease,
        lock_path=tmp_path / "recovery.execution.lock",
    )
    second = compose_file_locked_recovery_execution(
        lease,
        lock_path=tmp_path / "recovery.execution.lock",
    )

    with first.execution(
        "controller-a",
        "a" * 64,
        ttl_seconds=60.0,
    ) as owned:
        assert owned.assert_owned().owner_id == "controller-a"
        with pytest.raises(RecoveryLeaseBusy):
            with second.execution(
                "controller-b",
                "b" * 64,
                ttl_seconds=60.0,
            ):
                pass

    with second.execution(
        "controller-b",
        "b" * 64,
        ttl_seconds=60.0,
    ) as owned:
        assert owned.assert_owned().owner_id == "controller-b"
