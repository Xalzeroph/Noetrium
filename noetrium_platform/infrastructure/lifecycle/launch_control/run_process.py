from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.infrastructure.reliability.primitives.runtime_faults import FrozenRuntimeIdentityViolation, RuntimeOperationalHealthUnavailable
from noetrium_platform.infrastructure.lifecycle.service.api import ServiceContractDrift, ServiceLaunchContract, ExactServiceRuntimePort

from .contracts import RuntimeLaunchManifestPort


@dataclass(frozen=True, slots=True)
class RunLaunchIdentity:
    """Runtime identity that must remain unchanged when launching/resuming the Run process."""

    manifest_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.manifest_digest, str):
            raise TypeError("run launch identity digest must be text")
        digest = self.manifest_digest.strip().lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("run launch identity must be a SHA-256 manifest digest")
        object.__setattr__(self, "manifest_digest", digest)

    @classmethod
    def from_manifest(cls, manifest: RuntimeLaunchManifestPort) -> "RunLaunchIdentity":
        return cls(manifest.digest())

    def digest(self) -> str:
        return self.manifest_digest


@dataclass(frozen=True, slots=True)
class RunProcessBinding:
    identity: RunLaunchIdentity
    launch_contract: ServiceLaunchContract
    runtime: ExactServiceRuntimePort

    def __post_init__(self) -> None:
        if self.launch_contract.generation != self.identity.digest():
            raise ValueError("run service generation must equal frozen Run launch identity digest")


class RunProcessBindingError(FrozenRuntimeIdentityViolation):
    pass


class ExactRunProcessPort:
    """RunProcessPort backed by the generic service supervisor, independent of participant kinds."""

    def __init__(self, binding: RunProcessBinding) -> None:
        self.binding = binding

    def _verify(self, manifest: RuntimeLaunchManifestPort) -> None:
        expected = RunLaunchIdentity.from_manifest(manifest)
        if expected != self.binding.identity:
            raise RunProcessBindingError("run launch manifest differs from Run launch identity")
        if self.binding.launch_contract.generation != expected.digest():
            raise RunProcessBindingError("Run launch contract generation drift")

    def reconcile(self, manifest: RuntimeLaunchManifestPort) -> tuple[str, ...]:
        self._verify(manifest)
        contract = self.binding.launch_contract
        try:
            observation = self.binding.runtime.reconcile_exact(contract)
        except ServiceContractDrift as exc:
            raise RunProcessBindingError("run service runtime contract drift") from exc
        if not observation.state_present:
            return ("run-reconcile:no-state",)
        status = "missing" if observation.process is None else f"exact:{observation.process.start_identity}"
        return tuple(observation.evidence_refs) + (f"run-reconcile:{status}",)

    def start_exact(self, manifest: RuntimeLaunchManifestPort) -> tuple[str, ...]:
        self._verify(manifest)
        try:
            report = self.binding.runtime.start_exact(self.binding.launch_contract)
        except ServiceContractDrift as exc:
            raise RunProcessBindingError("run service runtime contract drift") from exc
        return tuple(report.evidence_refs) + (f"run-running:{report.contract_digest}",)

    def final_status(self, manifest: RuntimeLaunchManifestPort) -> tuple[str, ...]:
        self._verify(manifest)
        try:
            ready = self.binding.runtime.verify_ready_exact(self.binding.launch_contract)
        except ServiceContractDrift as exc:
            raise RunProcessBindingError("run service runtime contract drift") from exc
        except RuntimeError as exc:
            raise RuntimeOperationalHealthUnavailable("Run process is not running at FINAL_STATUS") from exc
        return tuple(ready.evidence_refs) + (
            ready.ready_evidence_ref,
            f"run-final:{ready.process.start_identity}:{manifest.experiment_spec_digest}",
        )


__all__ = ["ExactRunProcessPort", "RunLaunchIdentity", "RunProcessBinding", "RunProcessBindingError"]
