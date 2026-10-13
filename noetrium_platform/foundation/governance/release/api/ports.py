from __future__ import annotations

from pathlib import Path
from typing import ContextManager, Protocol

from .contracts import (
    ActiveReleasePin,
    ReleaseConsumerQuiescence,
    ReleaseQualityEvidence,
    ReleaseRegressionEvidence,
    ReleaseQuiescenceProof,
    ReleaseVerificationEvidence,
    ReleaseVerificationReport,
)


class ReleaseQualityEvidencePort(Protocol):
    """Build quality evidence without making release runtime own its sources."""

    def build(self, root: Path) -> ReleaseQualityEvidence: ...


class ReleaseRegressionPort(Protocol):
    """Execute or safely resume the exact local regression inventory."""

    def run(self, root: Path, *, source_manifest_digest: str) -> ReleaseRegressionEvidence: ...


class ReleaseVerifierPort(Protocol):
    """Verify one concrete release artifact using release-domain semantics."""

    def verify(self) -> ReleaseVerificationReport: ...


class ReleaseVerificationEvidencePort(Protocol):
    """Prove one concrete release artifact/tree and export stable verification evidence."""

    def read_release_verification_evidence(self) -> ReleaseVerificationEvidence: ...


class ReleasePinStorePort(Protocol):
    def lifecycle(self, control_id: str, runtime_manifest_digest: str) -> ContextManager[object]: ...
    def get(self, control_id: str, runtime_manifest_digest: str) -> ActiveReleasePin | None: ...
    def acquire(self, control_id: str, runtime_manifest_digest: str, release_digest: str) -> ActiveReleasePin: ...
    def release(self, control_id: str, runtime_manifest_digest: str) -> None: ...
    def active_for_release(self, release_digest: str) -> tuple[ActiveReleasePin, ...]: ...
    def assert_unpinned(self, release_digest: str) -> None: ...


class ReleaseConsumerQuiescenceProbe(Protocol):
    def observe(self, pin: ActiveReleasePin) -> ReleaseConsumerQuiescence: ...


class ReleaseQuiescenceProofProvider(Protocol):
    def prove(self, pin: ActiveReleasePin) -> ReleaseQuiescenceProof: ...


__all__ = [
    "ReleaseConsumerQuiescenceProbe",
    "ReleasePinStorePort",
    "ReleaseQualityEvidencePort",
    "ReleaseRegressionPort",
    "ReleaseQuiescenceProofProvider",
    "ReleaseVerificationEvidencePort",
    "ReleaseVerifierPort",
]
