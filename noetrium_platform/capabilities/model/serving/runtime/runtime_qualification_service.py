from __future__ import annotations

from noetrium_platform.capabilities.model.serving.api import (
    FrozenDeploymentIdentity,
    RuntimeQualificationPublication,
    ServiceHeartbeat,
)

from ..api.qualified_deployment import QualifiedDeploymentManifest
from ..api.runtime_qualification import build_runtime_qualification_receipt
from ..api.runtime_qualification_ports import RuntimeQualificationEvidenceStorePort


class RuntimeQualificationPublisher:
    """Model-OS authority for qualification semantics and durable receipt publication."""

    def __init__(
        self,
        evidence_store: RuntimeQualificationEvidenceStorePort,
        deployments: tuple[QualifiedDeploymentManifest, ...],
    ) -> None:
        ids = [item.deployment_id for item in deployments]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate deployment in runtime qualification publisher")
        self._evidence_store = evidence_store
        self._deployments = {item.deployment_id: item for item in deployments}

    @staticmethod
    def _assert_frozen_identity(
        frozen: FrozenDeploymentIdentity,
        deployment: QualifiedDeploymentManifest,
    ) -> None:
        if deployment.digest() != frozen.deployment_digest:
            raise ValueError("runtime qualification deployment digest drift")
        if deployment.stack.digest() != frozen.stack_digest:
            raise ValueError("runtime qualification stack digest drift")
        if deployment.stack.artifacts.digest() != frozen.artifact_digest:
            raise ValueError("runtime qualification artifact digest drift")
        if deployment.stack.runtime.digest() != frozen.runtime_identity_digest:
            raise ValueError("runtime qualification runtime identity drift")
        if deployment.certificate.digest() != frozen.qualification_certificate_digest:
            raise ValueError("runtime qualification certificate digest drift")
        if deployment.host_identity_digest != frozen.host_identity_digest:
            raise ValueError("runtime qualification host identity drift")
        if deployment.placement.gpu_uuids != frozen.gpu_uuids:
            raise ValueError("runtime qualification placement drift")

    def qualify_and_publish(
        self,
        runtime_manifest_digest: str,
        deployment: FrozenDeploymentIdentity,
        heartbeat: ServiceHeartbeat,
        *,
        required_roles: tuple[str, ...],
        evidence_refs: tuple[str, ...],
        max_heartbeat_age_seconds: float,
    ) -> RuntimeQualificationPublication:
        concrete = self._deployments.get(deployment.deployment_id)
        if concrete is None:
            raise ValueError("runtime qualification deployment is not registered")
        self._assert_frozen_identity(deployment, concrete)
        receipt = build_runtime_qualification_receipt(
            concrete,
            heartbeat,
            required_roles=required_roles,
            evidence_refs=evidence_refs,
            max_heartbeat_age_seconds=max_heartbeat_age_seconds,
        )
        evidence_ref = self._evidence_store.publish(runtime_manifest_digest, receipt)
        return RuntimeQualificationPublication(
            deployment_id=deployment.deployment_id,
            receipt_digest=receipt.digest(),
            evidence_ref=evidence_ref,
        )


__all__ = ["RuntimeQualificationPublisher"]
