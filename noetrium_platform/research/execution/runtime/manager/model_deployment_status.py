from __future__ import annotations

from noetrium_platform.research.execution.api import DeploymentStatusIdentity
from noetrium_platform.evidence.observability.status.api import HealthState, SubsystemSnapshot

from .status_ports import ServiceHeartbeatStatusPort


class ModelDeploymentStatusProbe:
    def __init__(
        self,
        deployment: DeploymentStatusIdentity,
        heartbeats: ServiceHeartbeatStatusPort,
        *,
        heartbeat_max_age_seconds: float,
    ) -> None:
        if heartbeat_max_age_seconds <= 0:
            raise ValueError("heartbeat_max_age_seconds must be positive")
        self._deployment = deployment
        self._heartbeats = heartbeats
        self._heartbeat_max_age_seconds = heartbeat_max_age_seconds

    def snapshot(self) -> SubsystemSnapshot:
        deployment = self._deployment
        dep_id = deployment.deployment_id
        refs = [f"stack:{deployment.stack_digest}", f"certificate:{deployment.qualification_digest}"]
        observation = self._heartbeats.observe(dep_id)
        heartbeat = observation.heartbeat
        refs.extend(observation.evidence_refs)
        if heartbeat is None:
            return SubsystemSnapshot(
                f"model:{dep_id}",
                HealthState.FAILED,
                "heartbeat missing",
                evidence=tuple(refs),
                next_commands=(f"inspect service state for {dep_id}",),
                reason_codes=("heartbeat_missing",),
            )

        reasons: list[str] = []
        if heartbeat.stack_digest != deployment.stack_digest:
            reasons.append("stack_digest_drift")
        if not heartbeat.ready:
            reasons.append("not_ready")
        if heartbeat.qualification_digest != deployment.qualification_digest:
            reasons.append("qualification_digest_drift")
        age = heartbeat.age()
        if age > self._heartbeat_max_age_seconds:
            reasons.append("stale_heartbeat")
        refs.append(f"pid:{heartbeat.pid}")
        return SubsystemSnapshot(
            f"model:{dep_id}",
            HealthState.FAILED if reasons else HealthState.READY,
            "ready/exact-qualified" if not reasons else ";".join(
                f"stale_heartbeat:{age:.1f}s" if reason == "stale_heartbeat" else reason
                for reason in reasons
            ),
            evidence=tuple(refs),
            next_commands=(f"noetrium-forensics debug-service {dep_id}",) if reasons else (),
            reason_codes=tuple(reasons),
        )


__all__ = ["ModelDeploymentStatusProbe"]
