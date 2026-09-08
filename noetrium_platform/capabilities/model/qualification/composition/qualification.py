"""Composition root for the deployment qualification seams."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from noetrium_platform.infrastructure.lifecycle.process.api import LocalCommandRunnerPort

from noetrium_platform.capabilities.model.qualification.api import (
    DeploymentCapabilityProbePort,
    DeploymentQualificationApplicationPort,
    DeploymentQualificationApplicationStorePort,
    DeploymentQualificationEvidenceRecord,
    DeploymentQualificationEvidenceStorePort,
    DeploymentQualificationPlan,
    DeploymentQualificationPort,
    DeploymentQualificationRequest,
    DeploymentQualificationRuntimePort,
    DeploymentQualificationRuntimeStorePort,
)
from noetrium_platform.capabilities.model.qualification.providers.qualification_probe import LocalDeploymentCapabilityProbe
from noetrium_platform.capabilities.model.qualification.providers.qualification_evidence import (
    FileDeploymentQualificationEvidenceStore,
)
from noetrium_platform.capabilities.model.qualification.providers.qualification_application import (
    FileDeploymentQualificationApplicationStore,
)
from noetrium_platform.capabilities.model.qualification.providers.python_package_installer import (
    PythonEnvironmentQualificationPackageInstaller,
)
from noetrium_platform.capabilities.model.qualification.providers.python_runtime_probe import (
    PythonEnvironmentRuntimeProbe,
)
from noetrium_platform.capabilities.model.qualification.providers.qualification_runtime import (
    FileDeploymentQualificationRuntimeStore,
)
from noetrium_platform.capabilities.model.qualification.runtime.application import DeploymentQualificationPlanApplier
from noetrium_platform.capabilities.model.qualification.runtime.qualification import DeploymentQualificationResolver
from noetrium_platform.capabilities.model.qualification.runtime.runtime_qualification import (
    DeploymentQualificationRuntimeVerifier,
)


class LocalDeploymentQualification(DeploymentQualificationPort):
    """Composition-selected implementation of the pure qualification port."""

    def __init__(
        self,
        probe: DeploymentCapabilityProbePort,
        resolver: DeploymentQualificationResolver,
        evidence: DeploymentQualificationEvidenceStorePort,
    ) -> None:
        self._probe = probe
        self._resolver = resolver
        self._evidence = evidence

    def qualify(self, request: DeploymentQualificationRequest) -> DeploymentQualificationPlan:
        facts = self._probe.capture(request)
        plan = self._resolver.resolve(request, facts)
        self._evidence.publish(
            DeploymentQualificationEvidenceRecord(
                captured_at_unix=facts.captured_at_unix,
                request=request,
                facts=facts,
                plan=plan,
            )
        )
        return plan


@dataclass(frozen=True, slots=True)
class DeploymentQualificationAuthorities:
    qualification: DeploymentQualificationPort
    evidence: DeploymentQualificationEvidenceStorePort
    application: DeploymentQualificationApplicationPort
    applications: DeploymentQualificationApplicationStorePort
    runtime: DeploymentQualificationRuntimePort
    runtimes: DeploymentQualificationRuntimeStorePort


def build_local_deployment_qualification(
    evidence_root: Path,
    package_manager,
    execution,
    local_commands: LocalCommandRunnerPort,
) -> DeploymentQualificationAuthorities:
    evidence = FileDeploymentQualificationEvidenceStore(evidence_root)
    applications = FileDeploymentQualificationApplicationStore(evidence_root / "applications")
    runtimes = FileDeploymentQualificationRuntimeStore(evidence_root / "runtime")
    return DeploymentQualificationAuthorities(
        qualification=LocalDeploymentQualification(
            LocalDeploymentCapabilityProbe(local_commands),
            DeploymentQualificationResolver(),
            evidence,
        ),
        evidence=evidence,
        application=DeploymentQualificationPlanApplier(
            evidence,
            PythonEnvironmentQualificationPackageInstaller(package_manager),
            applications,
        ),
        applications=applications,
        runtime=DeploymentQualificationRuntimeVerifier(
            evidence,
            applications,
            PythonEnvironmentRuntimeProbe(execution),
            runtimes,
        ),
        runtimes=runtimes,
    )


__all__ = [
    "DeploymentQualificationAuthorities",
    "LocalDeploymentQualification",
    "build_local_deployment_qualification",
]
