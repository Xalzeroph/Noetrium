from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.infrastructure.reliability.primitives.runtime_faults import FrozenRuntimeIdentityViolation, RuntimeOperationalHealthUnavailable
from noetrium_platform.infrastructure.lifecycle.service.api import ServiceContractDrift, ServiceLaunchContract, ExactServiceRuntimePort
from .contracts import RuntimeLaunchManifestPort
from noetrium_platform.capabilities.model.serving.api import FrozenDeploymentSet


@dataclass(frozen=True, slots=True)
class DeploymentServiceBinding:
    """Composition-time link between one frozen deployment and one service supervisor."""

    deployment_id: str
    launch_contract: ServiceLaunchContract
    runtime: ExactServiceRuntimePort


class DeploymentServiceBindingError(FrozenRuntimeIdentityViolation):
    pass


class ExactDeploymentServicePort:
    """ServiceRuntimePort for an exact frozen model deployment set.

    This class owns *binding validation and orchestration only*. Process lifecycle
    remains inside each ExactServiceSupervisor; model qualification remains outside.
    """

    def __init__(self, bindings: tuple[DeploymentServiceBinding, ...]) -> None:
        ids = [binding.deployment_id for binding in bindings]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate deployment service binding")
        self._bindings = {binding.deployment_id: binding for binding in bindings}

    @staticmethod
    def _validate_binding(binding: DeploymentServiceBinding, deployment) -> None:
        contract = binding.launch_contract
        if binding.deployment_id != deployment.deployment_id:
            raise DeploymentServiceBindingError("deployment binding identity mismatch")
        if contract.generation != deployment.deployment_digest:
            raise DeploymentServiceBindingError("service generation must equal frozen deployment digest")
        if contract.artifact_digest != deployment.artifact_digest:
            raise DeploymentServiceBindingError("service artifact closure drift")
        if contract.runtime_identity_digest != deployment.runtime_identity_digest:
            raise DeploymentServiceBindingError("service runtime-build identity drift")

    def _ordered(self, deployments: FrozenDeploymentSet) -> tuple[DeploymentServiceBinding, ...]:
        frozen = deployments.ordered_deployments()
        expected = {deployment.deployment_id for deployment in frozen}
        actual = set(self._bindings)
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            raise DeploymentServiceBindingError(f"service binding set drift: missing={missing}, extra={extra}")
        result: list[DeploymentServiceBinding] = []
        for deployment in frozen:
            binding = self._bindings[deployment.deployment_id]
            self._validate_binding(binding, deployment)
            result.append(binding)
        return tuple(result)

    def _assert_manifest(self, manifest: RuntimeLaunchManifestPort, deployments: FrozenDeploymentSet) -> None:
        expected = tuple(sorted(manifest.qualified_deployment_digests))
        actual = tuple(sorted(deployment.deployment_digest for deployment in deployments.deployments))
        if expected != actual:
            raise DeploymentServiceBindingError("runtime manifest/deployment set drift")

    def reconcile(
        self,
        manifest: RuntimeLaunchManifestPort,
        deployments: FrozenDeploymentSet,
    ) -> tuple[str, ...]:
        self._assert_manifest(manifest, deployments)
        refs: list[str] = []
        for binding in self._ordered(deployments):
            contract = binding.launch_contract
            try:
                observation = binding.runtime.reconcile_exact(contract)
            except ServiceContractDrift as exc:
                raise DeploymentServiceBindingError("service runtime contract drift") from exc
            if not observation.state_present:
                refs.append(f"service-reconcile:{binding.deployment_id}:no-state")
                continue
            refs.extend(observation.evidence_refs)
            if observation.process is None:
                refs.append(f"service-reconcile:{binding.deployment_id}:missing")
            else:
                refs.append(f"service-reconcile:{binding.deployment_id}:exact:{observation.process.start_identity}")
        return tuple(refs)

    def start_exact(
        self,
        manifest: RuntimeLaunchManifestPort,
        deployments: FrozenDeploymentSet,
    ) -> tuple[str, ...]:
        self._assert_manifest(manifest, deployments)
        refs: list[str] = []
        for binding in self._ordered(deployments):
            try:
                report = binding.runtime.start_exact(binding.launch_contract)
            except ServiceContractDrift as exc:
                raise DeploymentServiceBindingError("service runtime contract drift") from exc
            refs.extend(report.evidence_refs)
            refs.append(f"service-running:{binding.deployment_id}:{report.contract_digest}")
        return tuple(refs)

    def verify_ready(
        self,
        manifest: RuntimeLaunchManifestPort,
        deployments: FrozenDeploymentSet,
    ) -> tuple[str, ...]:
        self._assert_manifest(manifest, deployments)
        refs: list[str] = []
        for binding in self._ordered(deployments):
            try:
                ready = binding.runtime.verify_ready_exact(binding.launch_contract)
            except (ServiceContractDrift, RuntimeError) as exc:
                raise RuntimeOperationalHealthUnavailable(
                    f"service {binding.deployment_id} is not exactly ready"
                ) from exc
            refs.extend(ready.evidence_refs)
            refs.extend((
                ready.ready_evidence_ref,
                f"service-process:{binding.deployment_id}:{ready.process.start_identity}",
            ))
        return tuple(refs)

    def final_status(
        self,
        manifest: RuntimeLaunchManifestPort,
        deployments: FrozenDeploymentSet,
    ) -> tuple[str, ...]:
        ready = self.verify_ready(manifest, deployments)
        return ready + (f"service-set-exact:{manifest.digest()}",)


__all__ = [
    "DeploymentServiceBinding",
    "DeploymentServiceBindingError",
    "ExactDeploymentServicePort",
]
