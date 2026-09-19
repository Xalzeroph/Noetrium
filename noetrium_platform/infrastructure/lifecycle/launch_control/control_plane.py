from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from noetrium_platform.capabilities.model.serving.api import FrozenDeploymentSet

from .contracts import RuntimeAction, RuntimeLaunchManifestPort
from .controller import ExactRuntimeController, RuntimeControlAdapter, RuntimeControlReport
from .execution_guard import RuntimeActionExecutionGuard
from .host_ports import HostRuntimeVerificationPort
from .platform_ports import RuntimePlatformAuthorities
from .runtime_observer import RuntimeControlObserverPort, RuntimeObserverFailureSink


@dataclass(frozen=True, slots=True)
class RuntimeActionEvidence:
    action: RuntimeAction
    refs: tuple[str, ...]


class ServerRuntimeBindingPort(RuntimeControlAdapter, Protocol):
    def assert_manifest_binding(self, manifest: RuntimeLaunchManifestPort) -> None: ...


class ServerRuntimeAdapter(RuntimeControlAdapter):
    """Maps exact runtime actions to explicitly composed, narrow domain authorities."""

    def __init__(
        self,
        authorities: RuntimePlatformAuthorities,
        deployments: FrozenDeploymentSet,
        host_verification: HostRuntimeVerificationPort,
    ) -> None:
        self.authorities = authorities
        self.deployments = deployments
        self.host_verification = host_verification

    def assert_manifest_binding(self, manifest: RuntimeLaunchManifestPort) -> None:
        expected = tuple(sorted(manifest.qualified_deployment_digests))
        actual = tuple(sorted(deployment.deployment_digest for deployment in self.deployments.deployments))
        if expected != actual:
            raise ValueError("run launch manifest deployment digests do not match server deployment set")
        if manifest.role_model_manifest_digest != self.deployments.role_manifest_digest:
            raise ValueError("role-model manifest drift")

    def _verify_host_inventory(self, manifest: RuntimeLaunchManifestPort) -> tuple[str, ...]:
        return tuple(self.host_verification.verify_pre_start(manifest))

    def _verify_services_ready(self, manifest: RuntimeLaunchManifestPort) -> tuple[str, ...]:
        refs = tuple(self.authorities.services.verify_ready(manifest, self.deployments))
        return refs + tuple(self.host_verification.verify_post_ready(manifest))

    def _final_status(self, manifest: RuntimeLaunchManifestPort) -> tuple[str, ...]:
        return (
            tuple(self.authorities.services.final_status(manifest, self.deployments))
            + tuple(self.authorities.run.final_status(manifest))
        )

    def execute(self, action: RuntimeAction, manifest: RuntimeLaunchManifestPort) -> tuple[str, ...]:
        a = self.authorities
        d = self.deployments
        dispatch = {
            RuntimeAction.VERIFY_RELEASE: lambda: a.release.verify(manifest),
            RuntimeAction.VERIFY_PROMPT_PROMOTION: lambda: a.prompts.verify(manifest),
            RuntimeAction.VERIFY_HOST_INVENTORY: lambda: self._verify_host_inventory(manifest),
            RuntimeAction.VERIFY_DEPLOYMENTS: lambda: a.deployments.verify(manifest, d),
            RuntimeAction.RECONCILE_SERVICES: lambda: a.services.reconcile(manifest, d),
            RuntimeAction.START_EXACT_SERVICES: lambda: a.services.start_exact(manifest, d),
            RuntimeAction.VERIFY_SERVICES_READY: lambda: self._verify_services_ready(manifest),
            RuntimeAction.VERIFY_RUNTIME_QUALIFICATION: lambda: a.qualification.verify(manifest, d),
            RuntimeAction.VERIFY_PARTICIPANT_IMPLEMENTATIONS: lambda: a.implementations.verify(manifest),
            RuntimeAction.VERIFY_PARTICIPANT_RUNTIMES: lambda: a.runtimes.verify(manifest),
            RuntimeAction.VERIFY_PARTICIPANT_BINDINGS: lambda: a.bindings.verify(manifest),
            RuntimeAction.RECONCILE_RUN: lambda: a.run.reconcile(manifest),
            RuntimeAction.START_EXACT_RUN: lambda: a.run.start_exact(manifest),
            RuntimeAction.FINAL_STATUS: lambda: self._final_status(manifest),
        }
        return tuple(dispatch[action]())


class ServerRuntimeControlPlane:
    """One entrypoint for exact server bootstrap/resume. It never owns model-selection policy."""

    def __init__(self, controller: ExactRuntimeController, adapter: ServerRuntimeBindingPort) -> None:
        if controller.adapter is not adapter:
            raise ValueError("controller and server adapter must be the same runtime binding")
        self.controller = controller
        self.adapter = adapter

    def run_exact(
        self,
        manifest: RuntimeLaunchManifestPort,
        *,
        control_id: str,
        action_guard: RuntimeActionExecutionGuard | None = None,
        observer: RuntimeControlObserverPort | None = None,
        observer_failure_sink: RuntimeObserverFailureSink | None = None,
    ) -> RuntimeControlReport:
        self.adapter.assert_manifest_binding(manifest)
        return self.controller.run(
            manifest,
            control_id=control_id,
            action_guard=action_guard,
            observer=observer,
            observer_failure_sink=observer_failure_sink,
        )


__all__ = ["RuntimeActionEvidence", "ServerRuntimeAdapter", "ServerRuntimeBindingPort", "ServerRuntimeControlPlane"]
