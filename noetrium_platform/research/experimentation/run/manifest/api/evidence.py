from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from noetrium_platform.research.experimentation.run.api import RunArtifactSnapshotReceipt
from noetrium_platform.foundation.kernel.kernel import canonical_digest

_HEX = frozenset("0123456789abcdef")
EVIDENCE_BUNDLE_SCHEMA_VERSION = "2"


def _require_identity(value: object, field: str) -> str:
    text = _require_non_empty_string(value, field)
    if "/" in text or "\\" in text or text in {".", ".."}:
        raise ValueError(f"evidence bundle {field} is invalid")
    return text


def _require_non_empty_string(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"evidence bundle {field} must be a non-empty string")
    return value


def _require_sha256(value: object, field: str) -> str:
    if type(value) is not str or len(value) != 64 or any(character not in _HEX for character in value):
        raise ValueError(f"evidence bundle {field} must be SHA-256")
    return value

def _require_bool(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"evidence bundle {field} must be boolean")
    return value


class EvidenceBundleStatus(StrEnum):
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass(frozen=True, slots=True, order=True)
class EvidenceStreamDescriptor:
    stream_id: str
    family: str
    schema_version: str
    artifact_receipt: RunArtifactSnapshotReceipt
    required: bool
    source_of_truth: bool

    def __post_init__(self) -> None:
        _require_identity(self.stream_id, "stream_id")
        _require_non_empty_string(self.family, "stream family")
        _require_non_empty_string(self.schema_version, "stream schema_version")
        if type(self.artifact_receipt) is not RunArtifactSnapshotReceipt:
            raise ValueError("evidence stream requires a typed run artifact snapshot receipt")
        if self.artifact_receipt.record_count is None:
            raise ValueError("evidence stream artifact receipt must carry authoritative record_count")
        _require_bool(self.required, "stream required")
        _require_bool(self.source_of_truth, "stream source_of_truth")

    @property
    def artifact_ref(self) -> str:
        return self.artifact_receipt.artifact_ref

    @property
    def record_count(self) -> int:
        assert self.artifact_receipt.record_count is not None
        return self.artifact_receipt.record_count

    @property
    def content_sha256(self) -> str:
        return self.artifact_receipt.content_sha256


def _validate_source_stream_ids(values: tuple[str, ...]) -> None:
    if type(values) is not tuple or not values:
        raise ValueError("derived evidence artifact requires source streams")
    normalized = tuple(_require_identity(value, "derived source stream_id") for value in values)
    if tuple(sorted(set(normalized))) != normalized:
        raise ValueError("derived evidence source stream ids must be unique and ordered")


@dataclass(frozen=True, slots=True, order=True)
class DerivedEvidenceArtifact:
    artifact_id: str
    artifact_kind: str
    artifact_ref: str
    content_sha256: str
    derived_from_stream_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_identity(self.artifact_id, "artifact_id")
        _require_non_empty_string(self.artifact_kind, "artifact_kind")
        _require_non_empty_string(self.artifact_ref, "artifact_ref")
        _require_sha256(self.content_sha256, "artifact content_sha256")
        _validate_source_stream_ids(self.derived_from_stream_ids)


def _require_unique_ordered_ids(values: tuple[str, ...], field: str) -> None:
    if tuple(sorted(set(values))) != values:
        raise ValueError(f"{field} must be unique and ordered")


def _validate_stream_collection(
    streams: tuple[EvidenceStreamDescriptor, ...],
    run_id: str,
    status: EvidenceBundleStatus,
) -> tuple[str, ...]:
    if type(streams) is not tuple or not streams:
        raise ValueError("evidence bundle requires at least one stream")
    stream_ids: list[str] = []
    previous_stream_id: str | None = None
    has_authoritative_required = False
    for stream in streams:
        if type(stream) is not EvidenceStreamDescriptor:
            raise ValueError("evidence bundle streams must be typed descriptors")
        if previous_stream_id is not None and stream.stream_id <= previous_stream_id:
            raise ValueError("evidence streams must be unique and ordered")
        previous_stream_id = stream.stream_id
        stream_ids.append(stream.stream_id)
        if stream.artifact_receipt.run_id != run_id:
            raise ValueError("evidence stream artifact receipt belongs to a different run")
        if stream.required and stream.source_of_truth:
            has_authoritative_required = True
        if status is EvidenceBundleStatus.COMPLETE and stream.required and stream.record_count == 0:
            raise ValueError("complete evidence bundle cannot have an empty required stream")
    if not has_authoritative_required:
        raise ValueError("evidence bundle requires an authoritative required stream")
    return tuple(stream_ids)


def _validate_artifacts(
    artifacts: tuple[DerivedEvidenceArtifact, ...],
    stream_ids: tuple[str, ...],
) -> None:
    if type(artifacts) is not tuple or any(
        type(artifact) is not DerivedEvidenceArtifact for artifact in artifacts
    ):
        raise ValueError("derived evidence artifacts must be typed descriptors")
    artifact_ids = tuple(artifact.artifact_id for artifact in artifacts)
    _require_unique_ordered_ids(artifact_ids, "derived evidence artifacts")
    available = set(stream_ids)
    for artifact in artifacts:
        missing = set(artifact.derived_from_stream_ids) - available
        if missing:
            raise ValueError(f"derived evidence artifact references missing streams: {sorted(missing)}")


@dataclass(frozen=True, slots=True)
class EvidenceBundleManifest:
    """Immutable index over authority-finalized raw streams and rebuildable projections."""

    schema_version: str
    bundle_id: str
    run_id: str
    run_manifest_digest: str
    status: EvidenceBundleStatus
    source_checkpoint_id: str | None
    streams: tuple[EvidenceStreamDescriptor, ...]
    derived_artifacts: tuple[DerivedEvidenceArtifact, ...] = ()

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != EVIDENCE_BUNDLE_SCHEMA_VERSION:
            raise ValueError("evidence bundle schema_version is unsupported")
        _require_identity(self.bundle_id, "bundle_id")
        _require_identity(self.run_id, "run_id")
        _require_sha256(self.run_manifest_digest, "run_manifest_digest")
        if type(self.status) is not EvidenceBundleStatus:
            raise ValueError("evidence bundle status must be EvidenceBundleStatus")
        if self.source_checkpoint_id is not None:
            _require_non_empty_string(self.source_checkpoint_id, "source_checkpoint_id")
        stream_ids = _validate_stream_collection(self.streams, self.run_id, self.status)
        _validate_artifacts(self.derived_artifacts, stream_ids)

    @property
    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class EvidenceBundleReceipt:
    bundle_id: str
    run_id: str
    run_manifest_digest: str
    manifest_artifact_receipt: RunArtifactSnapshotReceipt

    def __post_init__(self) -> None:
        _require_identity(self.bundle_id, "receipt bundle_id")
        _require_identity(self.run_id, "receipt run_id")
        _require_sha256(self.run_manifest_digest, "receipt run_manifest_digest")
        if type(self.manifest_artifact_receipt) is not RunArtifactSnapshotReceipt:
            raise ValueError("evidence bundle receipt requires typed finalized manifest artifact")
        artifact = self.manifest_artifact_receipt
        if artifact.run_id != self.run_id:
            raise ValueError("evidence bundle manifest artifact belongs to a different run")
        if artifact.artifact_kind.value != "evidence" or artifact.record_count is not None:
            raise ValueError("evidence bundle manifest artifact receipt has invalid semantics")
        expected_ref = f"evidence/{self.bundle_id}/manifest.json"
        if artifact.artifact_ref != expected_ref:
            raise ValueError("evidence bundle manifest artifact ref does not match bundle identity")

    @property
    def manifest_ref(self) -> str:
        return self.manifest_artifact_receipt.artifact_ref

    @property
    def manifest_sha256(self) -> str:
        return self.manifest_artifact_receipt.content_sha256

    @property
    def digest(self) -> str:
        """Digest of the complete finalized evidence receipt identity."""
        return canonical_digest({
            "schema_version": EVIDENCE_BUNDLE_SCHEMA_VERSION,
            "bundle_id": self.bundle_id,
            "run_id": self.run_id,
            "run_manifest_digest": self.run_manifest_digest,
            "manifest_artifact_receipt": self.manifest_artifact_receipt,
        })



__all__ = [
    "DerivedEvidenceArtifact",
    "EVIDENCE_BUNDLE_SCHEMA_VERSION",
    "EvidenceBundleManifest",
    "EvidenceBundleReceipt",
    "EvidenceBundleStatus",
    "EvidenceStreamDescriptor",
]
