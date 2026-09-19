from __future__ import annotations

from noetrium_platform.capabilities.model.serving.api.qualified_deployment import QualifiedDeploymentManifest, RoleModelManifest
from noetrium_platform.capabilities.model.serving.api import (
    FrozenDeploymentIdentity,
    FrozenDeploymentSet,
    FrozenRoleAssignment,
)


def freeze_model_deployment(deployment: QualifiedDeploymentManifest) -> FrozenDeploymentIdentity:
    return FrozenDeploymentIdentity(
        deployment_id=deployment.deployment_id,
        deployment_digest=deployment.digest(),
        stack_digest=deployment.stack.digest(),
        artifact_digest=deployment.stack.artifacts.digest(),
        runtime_identity_digest=deployment.stack.runtime.digest(),
        qualification_certificate_digest=deployment.certificate.digest(),
        host_identity_digest=deployment.host_identity_digest,
        gpu_uuids=deployment.placement.gpu_uuids,
    )


def freeze_model_deployment_set(
    role_manifest: RoleModelManifest,
    deployments: tuple[QualifiedDeploymentManifest, ...],
) -> FrozenDeploymentSet:
    return FrozenDeploymentSet(
        role_manifest_digest=role_manifest.digest(),
        assignments=tuple(
            FrozenRoleAssignment(item.role, item.deployment_id)
            for item in role_manifest.assignments
        ),
        deployments=tuple(freeze_model_deployment(item) for item in deployments),
    )


__all__ = ["freeze_model_deployment", "freeze_model_deployment_set"]
