from __future__ import annotations

from noetrium_platform.infrastructure.reliability.primitives.runtime_faults import (
    FrozenRuntimeIdentityViolation,
    RuntimeOperationalHealthUnavailable,
)
from noetrium_platform.capabilities.model.serving.api import ServiceHeartbeat


def assert_exact_heartbeat(
    heartbeat: ServiceHeartbeat,
    *,
    deployment_id: str,
    stack_digest: str,
    max_age_seconds: float,
    require_ready: bool = True,
) -> ServiceHeartbeat:
    """Pure validation of one live heartbeat against frozen runtime identity."""

    if heartbeat.deployment_id != deployment_id:
        raise FrozenRuntimeIdentityViolation("service heartbeat deployment identity drift")
    if heartbeat.stack_digest != stack_digest:
        raise FrozenRuntimeIdentityViolation(f"service {deployment_id} stack digest drift")
    if heartbeat.age() > max_age_seconds:
        raise RuntimeOperationalHealthUnavailable(f"service {deployment_id} heartbeat stale")
    if require_ready and not heartbeat.ready:
        raise RuntimeOperationalHealthUnavailable(f"service {deployment_id} not ready")
    if require_ready and not heartbeat.qualification_digest:
        raise RuntimeOperationalHealthUnavailable(f"service {deployment_id} missing qualification evidence")
    return heartbeat


__all__ = ["ServiceHeartbeat", "assert_exact_heartbeat"]
