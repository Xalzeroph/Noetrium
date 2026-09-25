from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.governance.release.api import (
    ActiveReleasePinned,
    ReleasePinStorePort,
    ReleaseQuiescenceProof,
    ReleaseQuiescenceProofProvider,
)


class ReleaseNotQuiescent(ActiveReleasePinned):
    pass


@dataclass(frozen=True, slots=True)
class ReleasePinRetirementReport:
    proof: ReleaseQuiescenceProof
    retired: bool


class ActiveReleasePinRetirer:
    """Retires a pin only while holding the same lifecycle lock used by bootstrap."""

    def __init__(
        self,
        store: ReleasePinStorePort,
        proof_provider: ReleaseQuiescenceProofProvider,
    ) -> None:
        self.store = store
        self.proof_provider = proof_provider

    def retire(self, control_id: str, runtime_manifest_digest: str) -> ReleasePinRetirementReport:
        with self.store.lifecycle(control_id, runtime_manifest_digest):
            pin = self.store.get(control_id, runtime_manifest_digest)
            if pin is None:
                raise ActiveReleasePinned("active release pin does not exist")
            proof = self.proof_provider.prove(pin)
            if (
                proof.control_id != pin.control_id
                or proof.runtime_manifest_digest != pin.runtime_manifest_digest
                or proof.release_digest != pin.release_digest
            ):
                raise ActiveReleasePinned("quiescence proof identity does not match active release pin")
            if not proof.quiescent:
                raise ReleaseNotQuiescent("release is not quiescent: " + "; ".join(proof.blockers))
            self.store.release(control_id, runtime_manifest_digest)
            return ReleasePinRetirementReport(proof, True)


__all__ = ["ActiveReleasePinRetirer", "ReleaseNotQuiescent", "ReleasePinRetirementReport"]
