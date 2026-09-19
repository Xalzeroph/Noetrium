from __future__ import annotations

from noetrium_platform.infrastructure.reliability.primitives.runtime_faults import FrozenRuntimeIdentityViolation
from noetrium_platform.capabilities.model.serving.api import FrozenDeploymentSet, RuntimeQualificationPublisherPort

from .contracts import RuntimeLaunchManifestPort
from .heartbeat import assert_exact_heartbeat
from .heartbeat_ports import ServiceHeartbeatReadPort


class FrozenDeploymentVerificationPort:
    """Pure verification of the frozen model-serving topology; performs no process action."""

    def verify(
        self,
        manifest: RuntimeLaunchManifestPort,
        deployments: FrozenDeploymentSet,
    ) -> tuple[str, ...]:
        actual = tuple(sorted(deployment.deployment_digest for deployment in deployments.deployments))
        expected = tuple(sorted(manifest.qualified_deployment_digests))
        if actual != expected:
            raise FrozenRuntimeIdentityViolation("qualified deployment digest drift")
        if deployments.role_manifest_digest != manifest.role_model_manifest_digest:
            raise FrozenRuntimeIdentityViolation("role-model manifest drift")
        refs: list[str] = [f"role-model:{manifest.role_model_manifest_digest}"]
        for deployment in deployments.ordered_deployments():
            if deployment.host_identity_digest != manifest.target_host_identity_digest:
                raise FrozenRuntimeIdentityViolation(f"deployment {deployment.deployment_id} targets a different host identity")
            refs.extend((
                f"deployment:{deployment.deployment_id}:{deployment.deployment_digest}",
                f"model-stack:{deployment.deployment_id}:{deployment.stack_digest}",
                f"qualification-certificate:{deployment.deployment_id}:{deployment.qualification_certificate_digest}",
            ))
        return tuple(refs)


class HeartbeatRuntimeQualificationVerifier:
    """Post-start qualification binding based only on frozen deployments + live heartbeat evidence."""

    def __init__(
        self,
        heartbeat_store: ServiceHeartbeatReadPort,
        qualification_publisher: RuntimeQualificationPublisherPort,
        *,
        max_heartbeat_age_seconds: float,
    ) -> None:
        if max_heartbeat_age_seconds <= 0:
            raise ValueError("heartbeat age limit must be positive")
        self.heartbeat_store = heartbeat_store
        self.qualification_publisher = qualification_publisher
        self.max_heartbeat_age_seconds = max_heartbeat_age_seconds

    @staticmethod
    def _roles_for(deployment_id: str, deployments: FrozenDeploymentSet) -> tuple[str, ...]:
        return tuple(sorted(
            assignment.role
            for assignment in deployments.assignments
            if assignment.deployment_id == deployment_id
        ))

    def verify(
        self,
        manifest: RuntimeLaunchManifestPort,
        deployments: FrozenDeploymentSet,
    ) -> tuple[str, ...]:
        # Repeat the deployment identity proof here so this port remains safe in isolation.
        FrozenDeploymentVerificationPort().verify(manifest, deployments)
        refs: list[str] = []
        manifest_digest = manifest.digest()
        for deployment in deployments.ordered_deployments():
            heartbeat = assert_exact_heartbeat(
                self.heartbeat_store.read(deployment.deployment_id),
                deployment_id=deployment.deployment_id,
                stack_digest=deployment.stack_digest,
                max_age_seconds=self.max_heartbeat_age_seconds,
                require_ready=True,
            )
            heartbeat_ref = (
                f"heartbeat:{deployment.deployment_id}:{heartbeat.pid}:"
                f"{heartbeat.process_start_marker}:{heartbeat.timestamp}"
            )
            publication = self.qualification_publisher.qualify_and_publish(
                manifest_digest,
                deployment,
                heartbeat,
                required_roles=self._roles_for(deployment.deployment_id, deployments),
                evidence_refs=(heartbeat_ref,),
                max_heartbeat_age_seconds=self.max_heartbeat_age_seconds,
            )
            refs.extend((
                publication.evidence_ref,
                f"runtime-qualification:{deployment.deployment_id}:{publication.receipt_digest}",
            ))
        return tuple(refs)


__all__ = ["FrozenDeploymentVerificationPort", "HeartbeatRuntimeQualificationVerifier"]
