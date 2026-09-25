from __future__ import annotations

from dataclasses import dataclass
import time

from noetrium_platform.foundation.kernel.kernel import canonical_digest


class ActiveReleasePinned(RuntimeError):
    """A release lifecycle mutation conflicts with an authoritative active pin."""


@dataclass(frozen=True, slots=True)
class ActiveReleasePin:
    control_id: str
    runtime_manifest_digest: str
    release_digest: str
    acquired_at: float

    def __post_init__(self) -> None:
        if not self.control_id:
            raise ValueError("release pin control_id required")
        for value in (self.runtime_manifest_digest, self.release_digest):
            if len(value) != 64:
                raise ValueError("release pin digests must be SHA-256")
        if self.acquired_at <= 0:
            raise ValueError("release pin acquisition timestamp required")

    @classmethod
    def create(cls, control_id: str, runtime_manifest_digest: str, release_digest: str) -> "ActiveReleasePin":
        return cls(control_id, runtime_manifest_digest, release_digest, time.time())


@dataclass(frozen=True, slots=True)
class ReleaseConsumerQuiescence:
    consumer_id: str
    quiescent: bool
    summary: str
    evidence_refs: tuple[str, ...] = ()



@dataclass(frozen=True, slots=True)
class ReleaseQuiescenceProof:
    control_id: str
    runtime_manifest_digest: str
    release_digest: str
    observed_at: float
    blockers: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    @classmethod
    def create(
        cls,
        pin: ActiveReleasePin,
        *,
        blockers: tuple[str, ...],
        evidence_refs: tuple[str, ...],
    ) -> "ReleaseQuiescenceProof":
        return cls(
            pin.control_id,
            pin.runtime_manifest_digest,
            pin.release_digest,
            time.time(),
            blockers,
            evidence_refs,
        )

    @property
    def quiescent(self) -> bool:
        return not self.blockers

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class FileDigest:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class ReleaseManifest:
    schema_version: int
    files: tuple[FileDigest, ...]
    source_tree_sha256: str
    python_requires: str
    platform_code_version: str

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ReleaseQualityEvidence:
    architecture_report_sha256: str
    architecture_clean: bool
    no_degradation_findings: int
    silent_failure_findings: int
    algorithm_source_digest: str
    algorithm_clean: bool
    algorithm_blockers: int
    concurrency_source_digest: str
    concurrency_clean: bool
    concurrency_blockers: int
    performance_source_digest: str
    performance_clean: bool
    performance_blockers: int

    @property
    def clean(self) -> bool:
        return (
            self.architecture_clean
            and self.no_degradation_findings == 0
            and self.silent_failure_findings == 0
            and self.algorithm_clean
            and self.algorithm_blockers == 0
            and len(self.algorithm_source_digest) == 64
            and self.concurrency_clean
            and self.concurrency_blockers == 0
            and len(self.concurrency_source_digest) == 64
            and self.performance_clean
            and self.performance_blockers == 0
            and len(self.performance_source_digest) == 64
        )

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ReleaseRegressionEvidence:
    tests_collected: int
    tests_passed: int
    tests_skipped: int
    shard_count: int
    test_inventory_sha256: str
    runtime_sha256: str
    plan_sha256: str

    def __post_init__(self) -> None:
        if self.tests_collected <= 0:
            raise ValueError("release regression must collect tests")
        if min(self.tests_passed, self.tests_skipped, self.shard_count) < 0:
            raise ValueError("release regression counters cannot be negative")
        if self.tests_passed + self.tests_skipped != self.tests_collected:
            raise ValueError("release regression must account for every collected test")
        if self.shard_count <= 0:
            raise ValueError("release regression requires at least one shard")
        if any(len(value) != 64 for value in (self.test_inventory_sha256, self.runtime_sha256, self.plan_sha256)):
            raise ValueError("release regression identities must be SHA-256")

    @property
    def clean(self) -> bool:
        return self.tests_passed + self.tests_skipped == self.tests_collected


@dataclass(frozen=True, slots=True)
class ReleaseVerificationReport:
    clean: bool
    manifest_digest: str
    source_tree_sha256: str
    file_count: int
    errors: tuple[str, ...]


class ReleaseVerificationIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ReleaseVerificationEvidence:
    release_manifest_digest: str
    source_tree_sha256: str
    platform_code_version: str


__all__ = [
    "ActiveReleasePin",
    "ActiveReleasePinned",
    "FileDigest",
    "ReleaseConsumerQuiescence",
    "ReleaseManifest",
    "ReleaseQuiescenceProof",
    "ReleaseRegressionEvidence",
    "ReleaseVerificationEvidence",
    "ReleaseVerificationReport",
    "ReleaseVerificationIntegrityError",
]
