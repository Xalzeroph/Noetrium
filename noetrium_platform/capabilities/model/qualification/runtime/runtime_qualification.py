"""Post-materialization runtime qualification orchestration."""

from __future__ import annotations

from pathlib import Path

from noetrium_platform.capabilities.model.qualification.api import (
    DeploymentQualificationApplicationStorePort,
    DeploymentQualificationEvidenceStorePort,
    DeploymentQualificationRuntimePort,
    DeploymentQualificationRuntimeReceipt,
    DeploymentQualificationRuntimeRequest,
    DeploymentQualificationRuntimeStorePort,
    DeploymentRuntimeQualificationStatus,
    QualificationRuntimeProbePort,
)


class DeploymentQualificationRuntimeVerifier(DeploymentQualificationRuntimePort):
    """Verify an installed application without starting a serving process."""

    def __init__(
        self,
        evidence: DeploymentQualificationEvidenceStorePort,
        applications: DeploymentQualificationApplicationStorePort,
        probe: QualificationRuntimeProbePort,
        runtimes: DeploymentQualificationRuntimeStorePort,
    ) -> None:
        self._evidence = evidence
        self._applications = applications
        self._probe = probe
        self._runtimes = runtimes

    def qualify(
        self,
        request: DeploymentQualificationRuntimeRequest,
    ) -> DeploymentQualificationRuntimeReceipt:
        application = self._applications.get(request.application_digest)
        evidence = self._evidence.get(application.plan_digest)
        if application.status.value != "succeeded":
            return self._runtimes.publish(
                DeploymentQualificationRuntimeReceipt(
                    application_digest=application.application_digest,
                    plan_digest=application.plan_digest,
                    environment_id=application.environment_id,
                    backend=application.backend,
                    checks=(),
                    status=DeploymentRuntimeQualificationStatus.BLOCKED,
                    reasons=("application receipt is not successful",),
                )
            )
        if not application.backend:
            raise ValueError("successful application receipt has no backend")
        try:
            checks = self._probe.probe(
                application.environment_id,
                application.backend,
                Path(evidence.request.model_path),
                evidence.request.tensor_parallel,
            )
        except Exception as exc:
            receipt = DeploymentQualificationRuntimeReceipt(
                application_digest=application.application_digest,
                plan_digest=application.plan_digest,
                environment_id=application.environment_id,
                backend=application.backend,
                checks=(),
                status=DeploymentRuntimeQualificationStatus.FAILED,
                reasons=(f"runtime probe raised {type(exc).__name__}",),
            )
            self._runtimes.publish(receipt)
            raise
        reasons = tuple(
            f"runtime check {item.check} returned {item.return_code}"
            for item in checks
            if item.return_code != 0
        )
        receipt = DeploymentQualificationRuntimeReceipt(
            application_digest=application.application_digest,
            plan_digest=application.plan_digest,
            environment_id=application.environment_id,
            backend=application.backend,
            checks=checks,
            status=(
                DeploymentRuntimeQualificationStatus.PASSED
                if checks and not reasons
                else DeploymentRuntimeQualificationStatus.FAILED
            ),
            reasons=reasons,
        )
        return self._runtimes.publish(receipt)


__all__ = ["DeploymentQualificationRuntimeVerifier"]
