from __future__ import annotations

from noetrium_platform.evidence.observability.status.api import PlatformStatus
from noetrium_platform.composition.diagnostic_io import build_runtime_recovery_plan


def render_runtime_recovery_plan(status: PlatformStatus) -> dict[str, object]:
    """Read-only joined status + machine recovery decisions; never executes an action."""
    return build_runtime_recovery_plan(status)


__all__ = ["render_runtime_recovery_plan"]
