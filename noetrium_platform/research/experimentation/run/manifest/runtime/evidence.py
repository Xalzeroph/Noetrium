from __future__ import annotations

import hashlib
import json
from pathlib import Path

from noetrium_platform.research.experimentation.run.api import (
    RunArtifactKind,
    RunArtifactSealedError,
    RunArtifactSnapshotReceipt,
    RunArtifactStorePort,
    RunArtifactVerificationError,
)
from noetrium_platform.foundation.kernel.kernel import canonical_bytes

from ..api import (
    DerivedEvidenceArtifact,
    EvidenceBundleManifest,
    EvidenceBundleReceipt,
    EvidenceBundleStatus,
    EvidenceStreamDescriptor,
)


class EvidenceBundleDecodeError(ValueError):
    pass


def encode_evidence_bundle_manifest(manifest: EvidenceBundleManifest) -> bytes:
    return canonical_bytes(manifest, indent=2) + b"\n"


_BUNDLE_FIELDS = frozenset({
    "schema_version", "bundle_id", "run_id", "run_manifest_digest", "status",
    "source_checkpoint_id", "streams", "derived_artifacts",
})
_STREAM_FIELDS = frozenset({
    "stream_id", "family", "schema_version", "artifact_receipt", "required", "source_of_truth",
})
_RECEIPT_FIELDS = frozenset({
    "run_id", "artifact_ref", "artifact_kind", "generation", "content_sha256", "byte_size", "record_count",
})
_ARTIFACT_FIELDS = frozenset({
    "artifact_id", "artifact_kind", "artifact_ref", "content_sha256", "derived_from_stream_ids",
})


def _require_document(raw: bytes) -> dict[str, object]:
    if type(raw) is not bytes:
        raise TypeError("evidence bundle payload must be bytes")
    document = json.loads(raw.decode("utf-8"))
    if not isinstance(document, dict) or set(document) != _BUNDLE_FIELDS:
        raise TypeError("evidence bundle fields are not exact")
    return document


def _require_string(row: dict[str, object], field: str, scope: str) -> str:
    value = row[field]
    if type(value) is not str:
        raise TypeError(f"{scope} {field} must be a string")
    return value


def _require_int(value: object, field: str, scope: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{scope} {field} must be an integer")
    return value


def _decode_artifact_receipt(value: object) -> RunArtifactSnapshotReceipt:
    if not isinstance(value, dict) or set(value) != _RECEIPT_FIELDS:
        raise TypeError("evidence stream artifact_receipt fields are not exact")
    record_count = value["record_count"]
    if record_count is not None and type(record_count) is not int:
        raise TypeError("evidence stream artifact_receipt record_count must be an integer or null")
    try:
        kind = RunArtifactKind(_require_string(value, "artifact_kind", "artifact receipt"))
    except ValueError as exc:
        raise TypeError("evidence stream artifact_receipt kind is invalid") from exc
    return RunArtifactSnapshotReceipt(
        run_id=_require_string(value, "run_id", "artifact receipt"),
        artifact_ref=_require_string(value, "artifact_ref", "artifact receipt"),
        artifact_kind=kind,
        generation=_require_string(value, "generation", "artifact receipt"),
        content_sha256=_require_string(value, "content_sha256", "artifact receipt"),
        byte_size=_require_int(value["byte_size"], "byte_size", "artifact receipt"),
        record_count=record_count,
    )


def _decode_stream(row: object) -> EvidenceStreamDescriptor:
    if not isinstance(row, dict) or set(row) != _STREAM_FIELDS:
        raise TypeError("evidence stream fields are not exact")
    if type(row["required"]) is not bool or type(row["source_of_truth"]) is not bool:
        raise TypeError("evidence stream flags must be booleans")
    return EvidenceStreamDescriptor(
        stream_id=_require_string(row, "stream_id", "evidence stream"),
        family=_require_string(row, "family", "evidence stream"),
        schema_version=_require_string(row, "schema_version", "evidence stream"),
        artifact_receipt=_decode_artifact_receipt(row["artifact_receipt"]),
        required=row["required"],
        source_of_truth=row["source_of_truth"],
    )


def _decode_streams(value: object) -> tuple[EvidenceStreamDescriptor, ...]:
    if not isinstance(value, list):
        raise TypeError("evidence bundle streams must be a list")
    return tuple(_decode_stream(row) for row in value)


def _decode_artifact(row: object) -> DerivedEvidenceArtifact:
    if not isinstance(row, dict) or set(row) != _ARTIFACT_FIELDS:
        raise TypeError("derived evidence artifact fields are not exact")
    source_ids = row["derived_from_stream_ids"]
    if not isinstance(source_ids, list) or any(type(item) is not str for item in source_ids):
        raise TypeError("derived evidence source ids must be strings")
    return DerivedEvidenceArtifact(
        artifact_id=_require_string(row, "artifact_id", "derived evidence artifact"),
        artifact_kind=_require_string(row, "artifact_kind", "derived evidence artifact"),
        artifact_ref=_require_string(row, "artifact_ref", "derived evidence artifact"),
        content_sha256=_require_string(row, "content_sha256", "derived evidence artifact"),
        derived_from_stream_ids=tuple(source_ids),
    )


def _decode_artifacts(value: object) -> tuple[DerivedEvidenceArtifact, ...]:
    if not isinstance(value, list):
        raise TypeError("evidence bundle derived_artifacts must be a list")
    return tuple(_decode_artifact(row) for row in value)


def _decode_checkpoint(value: object) -> str | None:
    if value is not None and type(value) is not str:
        raise TypeError("evidence bundle source_checkpoint_id must be a string or null")
    return value


def _build_evidence_bundle(document: dict[str, object]) -> EvidenceBundleManifest:
    return EvidenceBundleManifest(
        schema_version=_require_string(document, "schema_version", "evidence bundle"),
        bundle_id=_require_string(document, "bundle_id", "evidence bundle"),
        run_id=_require_string(document, "run_id", "evidence bundle"),
        run_manifest_digest=_require_string(document, "run_manifest_digest", "evidence bundle"),
        status=EvidenceBundleStatus(_require_string(document, "status", "evidence bundle")),
        source_checkpoint_id=_decode_checkpoint(document["source_checkpoint_id"]),
        streams=_decode_streams(document["streams"]),
        derived_artifacts=_decode_artifacts(document["derived_artifacts"]),
    )


def decode_evidence_bundle_manifest(raw: bytes) -> EvidenceBundleManifest:
    try:
        return _build_evidence_bundle(_require_document(raw))
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise EvidenceBundleDecodeError(
            "evidence bundle violates the frozen manifest contract"
        ) from exc


def load_evidence_bundle_manifest(path: str | Path) -> EvidenceBundleManifest:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise EvidenceBundleDecodeError(f"evidence bundle manifest is not a regular file: {target}")
    try:
        return decode_evidence_bundle_manifest(target.read_bytes())
    except OSError as exc:
        raise EvidenceBundleDecodeError("evidence bundle manifest cannot be read") from exc


class RunArtifactEvidenceBundlePublisher:
    """Publish COMPLETE evidence only after artifact-authority verification."""

    def __init__(self, artifacts: RunArtifactStorePort) -> None:
        self._artifacts = artifacts

    def _verify_complete_streams(self, manifest: EvidenceBundleManifest) -> None:
        if manifest.status is not EvidenceBundleStatus.COMPLETE:
            return
        for stream in manifest.streams:
            try:
                verified = self._artifacts.verify_finalized(stream.artifact_receipt)
            except RunArtifactVerificationError as exc:
                raise ValueError(
                    f"complete evidence stream is not authority-finalized: {stream.stream_id}"
                ) from exc
            if verified != stream.artifact_receipt:
                raise ValueError(
                    f"complete evidence stream verification changed receipt: {stream.stream_id}"
                )

    def publish(self, manifest: EvidenceBundleManifest) -> EvidenceBundleReceipt:
        self._verify_complete_streams(manifest)
        encoded = canonical_bytes(manifest)
        manifest_artifact_ref = f"evidence/{manifest.bundle_id}/manifest.json"
        try:
            self._artifacts.publish_text(
                manifest_artifact_ref,
                encoded.decode("utf-8"),
                kind=RunArtifactKind.EVIDENCE,
            )
        except RunArtifactSealedError:
            # A retry may encounter the durable seal from an earlier successful publication.
            pass
        manifest_receipt = self._artifacts.finalize(
            manifest_artifact_ref,
            kind=RunArtifactKind.EVIDENCE,
            record_stream=False,
        )
        expected_sha256 = hashlib.sha256(encoded).hexdigest()
        if manifest_receipt.run_id != manifest.run_id:
            raise ValueError("published evidence manifest belongs to a different run")
        if manifest_receipt.content_sha256 != expected_sha256:
            raise ValueError("published evidence manifest content digest does not match encoded manifest")
        verified_manifest = self._artifacts.verify_finalized(manifest_receipt)
        if verified_manifest != manifest_receipt:
            raise ValueError("published evidence manifest verification changed receipt")
        return EvidenceBundleReceipt(
            manifest.bundle_id,
            manifest.run_id,
            manifest.run_manifest_digest,
            manifest_receipt,
        )


__all__ = [
    "EvidenceBundleDecodeError",
    "RunArtifactEvidenceBundlePublisher",
    "decode_evidence_bundle_manifest",
    "encode_evidence_bundle_manifest",
    "load_evidence_bundle_manifest",
]
