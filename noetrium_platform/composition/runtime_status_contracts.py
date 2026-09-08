from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from noetrium_platform.research.execution.api import DeploymentStatusIdentity
from noetrium_platform.infrastructure.lifecycle.session.api import PersistentSessionStatusConfig


@dataclass(frozen=True, slots=True)
class ServiceStatusBinding:
    service_id: str
    state_path: Path
    start_intent_root: Path


@dataclass(frozen=True, slots=True)
class RuntimeStatusLayout:
    runtime_state: Path
    runtime_history: Path
    heartbeat_root: Path
    recovery_lease: Path
    forensic_root: Path
    deployments: tuple[DeploymentStatusIdentity, ...]
    services: tuple[ServiceStatusBinding, ...]
    heartbeat_max_age_seconds: float = 30.0
    server_session: PersistentSessionStatusConfig | None = None

    def __post_init__(self) -> None:
        if self.heartbeat_max_age_seconds <= 0:
            raise ValueError("heartbeat_max_age_seconds must be positive")
        deployment_ids = [item.deployment_id for item in self.deployments]
        if len(deployment_ids) != len(set(deployment_ids)):
            raise ValueError("duplicate deployment_id in runtime status layout")
        service_ids = [item.service_id for item in self.services]
        if len(service_ids) != len(set(service_ids)):
            raise ValueError("duplicate service_id in runtime status layout")


__all__ = ["RuntimeStatusLayout", "ServiceStatusBinding"]
