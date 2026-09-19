from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .heartbeat import ServiceHeartbeat


@dataclass(frozen=True, slots=True)
class FrozenRoleAssignment:
    role: str
    deployment_id: str

    def __post_init__(self) -> None:
        if not self.role or not self.deployment_id:
            raise ValueError("frozen role assignment requires role and deployment_id")


@dataclass(frozen=True, slots=True)
class FrozenDeploymentIdentity:
    """Minimal cross-system identity for one qualified model deployment."""

    deployment_id: str
    deployment_digest: str
    stack_digest: str
    artifact_digest: str
    runtime_identity_digest: str
    qualification_certificate_digest: str
    host_identity_digest: str
    gpu_uuids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.deployment_id:
            raise ValueError("frozen deployment_id required")
        for name in (
            "deployment_digest",
            "stack_digest",
            "artifact_digest",
            "runtime_identity_digest",
            "qualification_certificate_digest",
            "host_identity_digest",
        ):
            value = getattr(self, name)
            if len(value) != 64:
                raise ValueError(f"{name} must be SHA-256")
        if not self.gpu_uuids or any(not item for item in self.gpu_uuids):
            raise ValueError("frozen deployment requires explicit GPU identities")


@dataclass(frozen=True, slots=True)
class FrozenDeploymentSet:
    """Runtime-control view of model topology; contains no Model-OS implementation objects."""

    role_manifest_digest: str
    assignments: tuple[FrozenRoleAssignment, ...]
    deployments: tuple[FrozenDeploymentIdentity, ...]

    def __post_init__(self) -> None:
        if len(self.role_manifest_digest) != 64:
            raise ValueError("role manifest digest must be SHA-256")
        ids = [item.deployment_id for item in self.deployments]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate deployment_id in frozen deployment set")
        roles = [item.role for item in self.assignments]
        if len(roles) != len(set(roles)):
            raise ValueError("each role must have exactly one frozen deployment assignment")
        known = set(ids)
        missing = {item.deployment_id for item in self.assignments} - known
        if missing:
            raise ValueError(f"role assignments reference unknown deployments: {sorted(missing)}")
        owner: dict[str, str] = {}
        for deployment in self.deployments:
            for gpu in deployment.gpu_uuids:
                prior = owner.get(gpu)
                if prior is not None and prior != deployment.deployment_id:
                    raise ValueError(
                        f"GPU {gpu} assigned to multiple independent deployments: {prior}, {deployment.deployment_id}"
                    )
                owner[gpu] = deployment.deployment_id

    def ordered_deployments(self) -> tuple[FrozenDeploymentIdentity, ...]:
        return tuple(sorted(self.deployments, key=lambda item: item.deployment_id))

    def roles_for(self, deployment_id: str) -> tuple[str, ...]:
        return tuple(sorted(
            item.role for item in self.assignments if item.deployment_id == deployment_id
        ))


@dataclass(frozen=True, slots=True)
class RuntimeQualificationPublication:
    deployment_id: str
    receipt_digest: str
    evidence_ref: str


class RuntimeQualificationPublisherPort(Protocol):
    def qualify_and_publish(
        self,
        runtime_manifest_digest: str,
        deployment: FrozenDeploymentIdentity,
        heartbeat: ServiceHeartbeat,
        *,
        required_roles: tuple[str, ...],
        evidence_refs: tuple[str, ...],
        max_heartbeat_age_seconds: float,
    ) -> RuntimeQualificationPublication: ...


__all__ = [
    "FrozenDeploymentIdentity",
    "FrozenDeploymentSet",
    "FrozenRoleAssignment",
    "RuntimeQualificationPublication",
    "RuntimeQualificationPublisherPort",
]
