from __future__ import annotations

from noetrium_platform.capabilities.model.request.prompt.api import ActivePromptEvidenceReadPort, PromptVerificationIntegrityError
from noetrium_platform.foundation.governance.release.api import ReleaseVerificationEvidencePort, ReleaseVerificationIntegrityError
from noetrium_platform.infrastructure.reliability.primitives.runtime_faults import FrozenRuntimeIdentityViolation

from noetrium_platform.capabilities.participant.core.api.frozen_manifests import (
    ParticipantImplementationInventory, ParticipantRuntimeBindingManifest, ParticipantRuntimeInventory,
)

from .contracts import RuntimeLaunchManifestPort



class FrozenReleaseVerifier:
    """Compare frozen runtime release identity with release-domain verification evidence only."""

    def __init__(self, evidence: ReleaseVerificationEvidencePort) -> None:
        self._evidence = evidence

    def verify(self, manifest: RuntimeLaunchManifestPort) -> tuple[str, ...]:
        try:
            evidence = self._evidence.read_release_verification_evidence()
        except ReleaseVerificationIntegrityError as exc:
            raise FrozenRuntimeIdentityViolation("release artifact verification failed") from exc
        if evidence.release_manifest_digest != manifest.release_digest:
            raise FrozenRuntimeIdentityViolation("runtime manifest release digest drift")
        return (
            f"release-manifest:{evidence.release_manifest_digest}",
            f"source-tree:{evidence.source_tree_sha256}",
            f"platform-version:{evidence.platform_code_version}",
        )


class ActivePromptPromotionVerifier:
    """Verify frozen prompt identity from a narrow Prompt OS evidence port only."""

    def __init__(self, evidence: ActivePromptEvidenceReadPort) -> None:
        self._evidence = evidence

    def verify(self, manifest: RuntimeLaunchManifestPort) -> tuple[str, ...]:
        try:
            evidence = self._evidence.read_active_verification_evidence()
        except PromptVerificationIntegrityError as exc:
            raise FrozenRuntimeIdentityViolation("ACTIVE prompt verification evidence is invalid") from exc
        if evidence.generation_payload_sha256 != manifest.prompt_generation_digest:
            raise FrozenRuntimeIdentityViolation("ACTIVE prompt generation payload digest drift")
        if evidence.promotion_evidence_digest != manifest.prompt_promotion_digest:
            raise FrozenRuntimeIdentityViolation("prompt promotion evidence digest drift")
        return (
            f"prompt-active:{evidence.generation_id}",
            f"prompt-generation:{evidence.generation_payload_sha256}",
            f"prompt-promotion:{evidence.promotion_evidence_digest}",
        )


class FrozenParticipantImplementationVerificationPort:
    """Verifies immutable implementation evidence only; no role/configuration or factory is visible here."""

    def __init__(self, inventory: ParticipantImplementationInventory) -> None:
        self.inventory = inventory

    def verify(self, manifest: RuntimeLaunchManifestPort) -> tuple[str, ...]:
        actual = self.inventory.digest()
        if actual != manifest.participant_implementation_inventory_digest:
            raise FrozenRuntimeIdentityViolation(
                "participant implementation inventory digest drift: "
                f"expected={manifest.participant_implementation_inventory_digest} actual={actual}"
            )
        return (f"participant-implementation-inventory:{actual}",) + tuple(
            f"participant-implementation:{row.kind}:{row.participant_id}:{row.digest()}"
            for row in self.inventory.implementations
        )


class FrozenParticipantRuntimeVerificationPort:
    """Verifies immutable participant session-runtime engine evidence independently of implementations."""

    def __init__(self, inventory: ParticipantRuntimeInventory) -> None:
        self.inventory = inventory

    def verify(self, manifest: RuntimeLaunchManifestPort) -> tuple[str, ...]:
        actual = self.inventory.digest()
        if actual != manifest.participant_runtime_inventory_digest:
            raise FrozenRuntimeIdentityViolation(
                "participant runtime inventory digest drift: "
                f"expected={manifest.participant_runtime_inventory_digest} actual={actual}"
            )
        return (f"participant-runtime-inventory:{actual}",) + tuple(
            f"participant-runtime:{row.runtime_id}:{row.runtime_version}:{row.digest()}"
            for row in self.inventory.runtimes
        )


class FrozenParticipantBindingVerificationPort:
    """Verifies the immutable run-binding artifact and its implementation-inventory linkage."""

    def __init__(self, binding_manifest: ParticipantRuntimeBindingManifest) -> None:
        self.binding_manifest = binding_manifest

    def verify(self, manifest: RuntimeLaunchManifestPort) -> tuple[str, ...]:
        if self.binding_manifest.implementation_inventory_digest != manifest.participant_implementation_inventory_digest:
            raise FrozenRuntimeIdentityViolation("participant binding manifest references another implementation inventory")
        if self.binding_manifest.runtime_inventory_digest != manifest.participant_runtime_inventory_digest:
            raise FrozenRuntimeIdentityViolation("participant binding manifest references another runtime inventory")
        actual = self.binding_manifest.digest()
        if actual != manifest.participant_binding_manifest_digest:
            raise FrozenRuntimeIdentityViolation(
                "participant runtime binding manifest digest drift: "
                f"expected={manifest.participant_binding_manifest_digest} actual={actual}"
            )
        return (f"participant-binding-manifest:{actual}",) + tuple(
            f"participant-binding:{row.role}:{row.implementation.digest()}:{row.runtime.digest()}:{row.configuration_digest}"
            for row in self.binding_manifest.bindings
        )


__all__ = [
    "ActivePromptPromotionVerifier",
    "FrozenParticipantImplementationVerificationPort",
    "FrozenParticipantRuntimeVerificationPort",
    "FrozenParticipantBindingVerificationPort",
    "FrozenReleaseVerifier",
]
