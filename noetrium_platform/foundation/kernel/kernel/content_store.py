"""Content-addressed evidence and artifact authorities."""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import Mapping, Protocol, runtime_checkable

from .canonical import canonical_bytes, canonical_digest, require_sha256, strict_json_loads
from .durability import InterprocessFileLock, atomic_replace_bytes


def _digest_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value


@dataclass(frozen=True, slots=True)
class ContentAddressedRef:
    kind: str
    content_digest: str
    media_type: str
    size_bytes: int
    metadata: Mapping[str, object] = field(default_factory=dict)
    ref_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.kind, "content ref kind")
        require_sha256(self.content_digest, "content_digest")
        _text(self.media_type, "content ref media_type")
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise ValueError("content ref size_bytes must be non-negative")
        if not isinstance(self.metadata, dict):
            raise TypeError("content ref metadata must be an object")
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "ref_digest", canonical_digest({
            "kind": self.kind,
            "content_digest": self.content_digest,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "metadata": self.metadata,
        }))


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    evidence_id: str
    claim: str
    refs: tuple[ContentAddressedRef, ...]
    provenance: Mapping[str, object] = field(default_factory=dict)
    bundle_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.evidence_id, "evidence_id")
        _text(self.claim, "claim")
        if type(self.refs) is not tuple or any(not isinstance(item, ContentAddressedRef) for item in self.refs):
            raise TypeError("evidence refs must be typed")
        if len({item.ref_digest for item in self.refs}) != len(self.refs):
            raise ValueError("evidence refs must be unique")
        if not isinstance(self.provenance, dict):
            raise TypeError("evidence provenance must be an object")
        object.__setattr__(self, "provenance", dict(self.provenance))
        object.__setattr__(self, "bundle_digest", canonical_digest({
            "evidence_id": self.evidence_id,
            "claim": self.claim,
            "refs": self.refs,
            "provenance": self.provenance,
        }))


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    artifact_id: str
    ref: ContentAddressedRef
    run_id: str
    role: str
    record_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.artifact_id, "artifact_id")
        if not isinstance(self.ref, ContentAddressedRef):
            raise TypeError("artifact ref must be typed")
        _text(self.run_id, "artifact run_id")
        _text(self.role, "artifact role")
        object.__setattr__(self, "record_digest", canonical_digest({
            "artifact_id": self.artifact_id,
            "ref": self.ref,
            "run_id": self.run_id,
            "role": self.role,
        }))


@runtime_checkable
class ContentAddressedStorePort(Protocol):
    def put(self, content: bytes, *, kind: str, media_type: str,
            metadata: Mapping[str, object] | None = None) -> ContentAddressedRef: ...
    def get(self, ref: ContentAddressedRef) -> bytes: ...
    def verify(self, ref: ContentAddressedRef) -> bool: ...


@runtime_checkable
class EvidenceStorePort(Protocol):
    def save_bundle(self, bundle: EvidenceBundle) -> EvidenceBundle: ...
    def load_bundle(self, evidence_id: str) -> EvidenceBundle | None: ...


@runtime_checkable
class RunArtifactStorePort(Protocol):
    def save_artifact(self, artifact: ArtifactRecord) -> ArtifactRecord: ...
    def load_artifact(self, artifact_id: str) -> ArtifactRecord | None: ...
class ContentAddressedStoreError(RuntimeError):
    """The content store cannot prove an immutable reference."""


class InMemoryContentAddressedStore(
    ContentAddressedStorePort, EvidenceStorePort, RunArtifactStorePort
):
    durability = "process_local"

    def __init__(self) -> None:
        self._content: dict[str, bytes] = {}
        self._bundles: dict[str, EvidenceBundle] = {}
        self._artifacts: dict[str, ArtifactRecord] = {}
        self._lock = RLock()

    def put(self, content: bytes, *, kind: str, media_type: str,
            metadata: Mapping[str, object] | None = None) -> ContentAddressedRef:
        if type(content) is not bytes:
            raise TypeError("content must be bytes")
        ref = ContentAddressedRef(
            kind, _digest_bytes(content), media_type, len(content),
            {} if metadata is None else dict(metadata),
        )
        with self._lock:
            prior = self._content.get(ref.content_digest)
            if prior is not None and prior != content:
                raise ContentAddressedStoreError("content digest collision")
            self._content[ref.content_digest] = content
        return ref

    def get(self, ref: ContentAddressedRef) -> bytes:
        if not isinstance(ref, ContentAddressedRef):
            raise TypeError("content ref must be typed")
        with self._lock:
            try:
                content = self._content[ref.content_digest]
            except KeyError as exc:
                raise ContentAddressedStoreError("content is missing") from exc
        if len(content) != ref.size_bytes or _digest_bytes(content) != ref.content_digest:
            raise ContentAddressedStoreError("content integrity mismatch")
        return content

    def verify(self, ref: ContentAddressedRef) -> bool:
        try:
            self.get(ref)
        except ContentAddressedStoreError:
            return False
        return True

    def save_bundle(self, bundle: EvidenceBundle) -> EvidenceBundle:
        if not isinstance(bundle, EvidenceBundle):
            raise TypeError("evidence store accepts EvidenceBundle")
        with self._lock:
            prior = self._bundles.get(bundle.evidence_id)
            if prior is not None and prior.bundle_digest != bundle.bundle_digest:
                raise ContentAddressedStoreError("evidence identity collision")
            self._bundles[bundle.evidence_id] = bundle
            return bundle

    def load_bundle(self, evidence_id: str) -> EvidenceBundle | None:
        _text(evidence_id, "evidence_id")
        with self._lock:
            return self._bundles.get(evidence_id)

    def save_artifact(self, artifact: ArtifactRecord) -> ArtifactRecord:
        if not isinstance(artifact, ArtifactRecord):
            raise TypeError("artifact store accepts ArtifactRecord")
        with self._lock:
            prior = self._artifacts.get(artifact.artifact_id)
            if prior is not None and prior.record_digest != artifact.record_digest:
                raise ContentAddressedStoreError("artifact identity collision")
            self._artifacts[artifact.artifact_id] = artifact
            return artifact

    def load_artifact(self, artifact_id: str) -> ArtifactRecord | None:
        _text(artifact_id, "artifact_id")
        with self._lock:
            return self._artifacts.get(artifact_id)
class DirectoryContentAddressedStore(
    ContentAddressedStorePort, EvidenceStorePort, RunArtifactStorePort
):
    """Crash-durable immutable blobs plus canonical reference indexes."""

    durability = "crash_durable"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.blobs = self.root / "blobs"
        self.refs = self.root / "refs"
        self.bundles = self.root / "evidence"
        self.artifacts = self.root / "artifacts"
        self.locks = self.root / "locks"
        for path in (self.blobs, self.refs, self.bundles, self.artifacts, self.locks):
            path.mkdir(parents=True, exist_ok=True)

    def _blob_path(self, digest: str) -> Path:
        return self.blobs / f"{digest}.bin"

    def _ref_path(self, digest: str) -> Path:
        return self.refs / f"{digest}.json"

    def put(self, content: bytes, *, kind: str, media_type: str,
            metadata: Mapping[str, object] | None = None) -> ContentAddressedRef:
        if type(content) is not bytes:
            raise TypeError("content must be bytes")
        ref = ContentAddressedRef(
            kind, _digest_bytes(content), media_type, len(content),
            {} if metadata is None else dict(metadata),
        )
        with InterprocessFileLock(self.locks / f"{ref.content_digest}.lock"):
            blob = self._blob_path(ref.content_digest)
            if blob.exists():
                if blob.read_bytes() != content:
                    raise ContentAddressedStoreError("content digest collision")
            else:
                atomic_replace_bytes(blob, content)
            atomic_replace_bytes(self._ref_path(ref.ref_digest), canonical_bytes({
                "kind": ref.kind,
                "content_digest": ref.content_digest,
                "media_type": ref.media_type,
                "size_bytes": ref.size_bytes,
                "metadata": dict(ref.metadata),
                "ref_digest": ref.ref_digest,
            }))
        return ref
    def get(self, ref: ContentAddressedRef) -> bytes:
        if not isinstance(ref, ContentAddressedRef):
            raise TypeError("content ref must be typed")
        path = self._blob_path(ref.content_digest)
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise ContentAddressedStoreError("content is missing") from exc
        if len(content) != ref.size_bytes or _digest_bytes(content) != ref.content_digest:
            raise ContentAddressedStoreError("content integrity mismatch")
        return content

    def verify(self, ref: ContentAddressedRef) -> bool:
        try:
            self.get(ref)
        except ContentAddressedStoreError:
            return False
        return True

    def save_bundle(self, bundle: EvidenceBundle) -> EvidenceBundle:
        if not isinstance(bundle, EvidenceBundle):
            raise TypeError("evidence store accepts EvidenceBundle")
        path = self.bundles / f"{bundle.evidence_id}.json"
        with InterprocessFileLock(self.locks / f"evidence-{bundle.evidence_id}.lock"):
            if path.exists():
                current = self.load_bundle(bundle.evidence_id)
                if current is not None and current.bundle_digest != bundle.bundle_digest:
                    raise ContentAddressedStoreError("evidence identity collision")
            atomic_replace_bytes(path, canonical_bytes({
                "evidence_id": bundle.evidence_id,
                "claim": bundle.claim,
                "refs": [self._ref_document(ref) for ref in bundle.refs],
                "provenance": dict(bundle.provenance),
                "bundle_digest": bundle.bundle_digest,
            }))
        return bundle

    @staticmethod
    def _ref_document(ref: ContentAddressedRef) -> dict[str, object]:
        return {
            "kind": ref.kind, "content_digest": ref.content_digest,
            "media_type": ref.media_type, "size_bytes": ref.size_bytes,
            "metadata": dict(ref.metadata), "ref_digest": ref.ref_digest,
        }
    def _read_json(self, path: Path) -> object:
        try:
            raw = path.read_bytes()
            value = strict_json_loads(raw)
            if canonical_bytes(value) != raw:
                raise ContentAddressedStoreError("content store record is not canonical")
            return value
        except ContentAddressedStoreError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise ContentAddressedStoreError("content store record is corrupt") from exc

    @staticmethod
    def _decode_ref(value: object) -> ContentAddressedRef:
        if not isinstance(value, dict):
            raise ContentAddressedStoreError("content ref is not an object")
        expected = {"kind", "content_digest", "media_type", "size_bytes", "metadata", "ref_digest"}
        if set(value) != expected:
            raise ContentAddressedStoreError("content ref fields are not exact")
        ref = ContentAddressedRef(
            value["kind"], value["content_digest"], value["media_type"],
            value["size_bytes"], value["metadata"],
        )
        if ref.ref_digest != value["ref_digest"]:
            raise ContentAddressedStoreError("content ref digest mismatch")
        return ref

    def load_bundle(self, evidence_id: str) -> EvidenceBundle | None:
        _text(evidence_id, "evidence_id")
        path = self.bundles / f"{evidence_id}.json"
        if not path.exists():
            return None
        value = self._read_json(path)
        if not isinstance(value, dict) or set(value) != {
            "evidence_id", "claim", "refs", "provenance", "bundle_digest",
        }:
            raise ContentAddressedStoreError("evidence record fields are not exact")
        refs = tuple(self._decode_ref(item) for item in value["refs"])
        bundle = EvidenceBundle(value["evidence_id"], value["claim"], refs, value["provenance"])
        if bundle.bundle_digest != value["bundle_digest"]:
            raise ContentAddressedStoreError("evidence digest mismatch")
        return bundle

    def load_artifact(self, artifact_id: str) -> ArtifactRecord | None:
        _text(artifact_id, "artifact_id")
        path = self.artifacts / f"{artifact_id}.json"
        if not path.exists():
            return None
        value = self._read_json(path)
        if not isinstance(value, dict) or set(value) != {
            "artifact_id", "ref", "run_id", "role", "record_digest",
        }:
            raise ContentAddressedStoreError("artifact record fields are not exact")
        artifact = ArtifactRecord(
            value["artifact_id"], self._decode_ref(value["ref"]),
            value["run_id"], value["role"],
        )
        if artifact.record_digest != value["record_digest"]:
            raise ContentAddressedStoreError("artifact digest mismatch")
        return artifact

    def save_artifact(self, artifact: ArtifactRecord) -> ArtifactRecord:
        if not isinstance(artifact, ArtifactRecord):
            raise TypeError("artifact store accepts ArtifactRecord")
        path = self.artifacts / f"{artifact.artifact_id}.json"
        with InterprocessFileLock(self.locks / f"artifact-{artifact.artifact_id}.lock"):
            prior = self.load_artifact(artifact.artifact_id)
            if prior is not None and prior.record_digest != artifact.record_digest:
                raise ContentAddressedStoreError("artifact identity collision")
            atomic_replace_bytes(path, canonical_bytes({
                "artifact_id": artifact.artifact_id,
                "ref": self._ref_document(artifact.ref),
                "run_id": artifact.run_id,
                "role": artifact.role,
                "record_digest": artifact.record_digest,
            }))
        return artifact


__all__ = [
    "ArtifactRecord",
    "ContentAddressedRef",
    "ContentAddressedStoreError",
    "ContentAddressedStorePort",
    "DirectoryContentAddressedStore",
    "EvidenceBundle",
    "EvidenceStorePort",
    "InMemoryContentAddressedStore",
    "RunArtifactStorePort",
]
