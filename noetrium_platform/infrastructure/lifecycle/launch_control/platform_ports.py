from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from noetrium_platform.capabilities.model.serving.api import FrozenDeploymentSet

from .contracts import RuntimeLaunchManifestPort


class ReleaseVerificationPort(Protocol):
    """Read-only authority for proving the frozen release identity."""

    def verify(self, manifest: RuntimeLaunchManifestPort) -> tuple[str, ...]: ...


class PromptPromotionVerificationPort(Protocol):
    """Read-only authority for proving prompt generation + promotion identity."""

    def verify(self, manifest: RuntimeLaunchManifestPort) -> tuple[str, ...]: ...


class DeploymentVerificationPort(Protocol):
    """Read-only authority for model deployment topology and immutable stack identity."""

    def verify(
        self,
        manifest: RuntimeLaunchManifestPort,
        deployments: FrozenDeploymentSet,
    ) -> tuple[str, ...]: ...


class ServiceRuntimePort(Protocol):
    """Owns service-process lifecycle only; it does not own release, prompts, or study policy."""

    def reconcile(
        self,
        manifest: RuntimeLaunchManifestPort,
        deployments: FrozenDeploymentSet,
    ) -> tuple[str, ...]: ...

    def start_exact(
        self,
        manifest: RuntimeLaunchManifestPort,
        deployments: FrozenDeploymentSet,
    ) -> tuple[str, ...]: ...

    def verify_ready(
        self,
        manifest: RuntimeLaunchManifestPort,
        deployments: FrozenDeploymentSet,
    ) -> tuple[str, ...]: ...

    def final_status(
        self,
        manifest: RuntimeLaunchManifestPort,
        deployments: FrozenDeploymentSet,
    ) -> tuple[str, ...]: ...


class RuntimeQualificationPort(Protocol):
    """Read-only authority for runtime qualification certificates/evidence."""

    def verify(
        self,
        manifest: RuntimeLaunchManifestPort,
        deployments: FrozenDeploymentSet,
    ) -> tuple[str, ...]: ...


class ParticipantImplementationVerificationPort(Protocol):
    """Read-only authority for implementation artifact/ABI availability only."""

    def verify(self, manifest: RuntimeLaunchManifestPort) -> tuple[str, ...]: ...


class ParticipantRuntimeVerificationPort(Protocol):
    """Read-only authority for participant session-runtime engine evidence only."""

    def verify(self, manifest: RuntimeLaunchManifestPort) -> tuple[str, ...]: ...


class ParticipantBindingVerificationPort(Protocol):
    """Read-only authority for exact role/implementation/runtime/configuration bindings only."""

    def verify(self, manifest: RuntimeLaunchManifestPort) -> tuple[str, ...]: ...


class RunProcessPort(Protocol):
    """Owns the run-process lifecycle only; it cannot mutate service/model policy."""

    def reconcile(self, manifest: RuntimeLaunchManifestPort) -> tuple[str, ...]: ...

    def start_exact(self, manifest: RuntimeLaunchManifestPort) -> tuple[str, ...]: ...

    def final_status(self, manifest: RuntimeLaunchManifestPort) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class RuntimePlatformAuthorities:
    """Immutable composition bundle of narrow runtime authorities; contains no orchestration behavior."""

    release: ReleaseVerificationPort
    prompts: PromptPromotionVerificationPort
    deployments: DeploymentVerificationPort
    services: ServiceRuntimePort
    qualification: RuntimeQualificationPort
    implementations: ParticipantImplementationVerificationPort
    runtimes: ParticipantRuntimeVerificationPort
    bindings: ParticipantBindingVerificationPort
    run: RunProcessPort


__all__ = [
    "ReleaseVerificationPort",
    "PromptPromotionVerificationPort",
    "DeploymentVerificationPort",
    "ServiceRuntimePort",
    "RuntimeQualificationPort",
    "ParticipantImplementationVerificationPort",
    "ParticipantRuntimeVerificationPort",
    "ParticipantBindingVerificationPort",
    "RunProcessPort",
    "RuntimePlatformAuthorities",
]
