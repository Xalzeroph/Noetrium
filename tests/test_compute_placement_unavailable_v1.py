from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputePlacementUnavailable,
    ComputeRequirement,
)
from noetrium_platform.infrastructure.resources.compute.composition import compose_compute_authority
from noetrium_platform.infrastructure.resources.lease.runtime import ManualLeaseClock


def test_compute_scheduler_reports_typed_capacity_exhaustion(tmp_path: Path) -> None:
    stack = compose_compute_authority(
        tmp_path / "compute.sqlite",
        clock=ManualLeaseClock(elapsed_seconds=1.0, wall_epoch_seconds=100.0),
    )
    requirement = ComputeRequirement(cpu_cores=1, memory_bytes=1)
    with pytest.raises(ComputePlacementUnavailable) as raised:
        stack.scheduler.allocate(
            "missing-capacity",
            PLATFORM_SCOPE,
            requirement,
            placement_scope=PLATFORM_SCOPE,
        )
    assert raised.value.requirement == requirement
