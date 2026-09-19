from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile
import zipfile

from noetrium_platform.foundation.governance.release.api import ReleaseManifest
from noetrium_platform.foundation.kernel.kernel import canonical_bytes
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import durable_replace_file
from .manifest import build_release_manifest
from .evidence import RELEASE_EVIDENCE_FILENAME, ReleaseEvidence, ReleaseEvidenceMismatch, load_release_evidence
from .authority import RELEASE_AUTHORITY_FILENAME, build_release_authority_receipt


class _HashingWriteSink:
    """Forward-only ZIP sink that hashes exactly the bytes published.

    ``zipfile`` switches to data-descriptor mode when the output is not seekable,
    so headers are never rewritten in place.  That makes a single-pass SHA-256
    exact while preserving deterministic member metadata.
    """

    def __init__(self, raw) -> None:
        self._raw = raw
        self._digest = hashlib.sha256()
        self._position = 0

    def write(self, data: bytes) -> int:
        written = self._raw.write(data)
        if written:
            view = memoryview(data)[:written]
            self._digest.update(view)
            self._position += written
        return written

    def tell(self) -> int:
        return self._position

    def flush(self) -> None:
        self._raw.flush()

    def seekable(self) -> bool:
        return False

    @property
    def sha256(self) -> str:
        return self._digest.hexdigest()


@dataclass(frozen=True, slots=True)
class ReleasePackagingPolicy:
    compression_level: int = 6

    def __post_init__(self) -> None:
        if not 0 <= int(self.compression_level) <= 9:
            raise ValueError("release ZIP compression level must be between 0 and 9")


@dataclass(frozen=True, slots=True)
class ReleasePackage:
    zip_path: str
    sha256: str
    manifest_digest: str
    file_count: int
    evidence_digest: str | None = None


class ReleasePackager:
    """Atomic, streaming, deterministic release package publisher.

    Release members are streamed directly into a same-directory temporary ZIP.
    Each source member is re-hashed while it is packaged and must match the frozen
    manifest.  Therefore a source edit racing packaging fails closed and a partial
    official ZIP is never published.
    """

    NORMALIZED_DT = (2026, 1, 1, 0, 0, 0)
    _COPY_CHUNK_BYTES = 1024 * 1024

    def __init__(self, policy: ReleasePackagingPolicy | None = None) -> None:
        self._policy = policy or ReleasePackagingPolicy()

    @classmethod
    def _zip_info(cls, name: str) -> zipfile.ZipInfo:
        info = zipfile.ZipInfo(name, cls.NORMALIZED_DT)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (0o644 & 0xFFFF) << 16
        info.create_system = 3
        return info

    def _stream_member(
        self,
        zf: zipfile.ZipFile,
        *,
        source: Path,
        info: zipfile.ZipInfo,
        expected_sha256: str,
        expected_size: int,
    ) -> None:
        digest = hashlib.sha256()
        size = 0
        info._compresslevel = self._policy.compression_level
        with source.open("rb") as src, zf.open(info, "w", force_zip64=True) as dst:
            while True:
                chunk = src.read(self._COPY_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
                dst.write(chunk)
        if size != expected_size:
            raise ReleaseEvidenceMismatch(f"source size drift while packaging: {info.filename}")
        if digest.hexdigest() != expected_sha256:
            raise ReleaseEvidenceMismatch(f"source hash drift while packaging: {info.filename}")



    def build(
        self,
        root: Path,
        zip_path: Path,
        *,
        version: str | None = None,
        evidence: ReleaseEvidence | None = None,
        manifest: ReleaseManifest | None = None,
    ) -> ReleasePackage:
        root = Path(root).resolve()
        frozen_manifest = manifest or build_release_manifest(root, platform_code_version=version)
        resolved_evidence = evidence
        evidence_path = root / RELEASE_EVIDENCE_FILENAME
        if resolved_evidence is None and evidence_path.exists():
            resolved_evidence = load_release_evidence(evidence_path)
        if resolved_evidence is not None:
            if not resolved_evidence.clean:
                raise ReleaseEvidenceMismatch("release evidence is not clean")
            if resolved_evidence.release_manifest_digest != frozen_manifest.digest():
                raise ReleaseEvidenceMismatch("release evidence does not bind the package manifest")

        manifest_bytes = canonical_bytes(frozen_manifest, indent=2)
        zip_path = Path(zip_path)
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{zip_path.name}.",
            suffix=".tmp",
            dir=zip_path.parent,
        )
        temp_path = Path(temp_name)
        published = False
        try:
            with os.fdopen(fd, "wb", buffering=1024 * 1024) as raw:
                sink = _HashingWriteSink(raw)
                with zipfile.ZipFile(
                    sink,
                    "w",
                    compression=zipfile.ZIP_DEFLATED,
                    compresslevel=self._policy.compression_level,
                    strict_timestamps=True,
                ) as zf:
                    for row in frozen_manifest.files:
                        source = root / row.path
                        self._stream_member(
                            zf,
                            source=source,
                            info=self._zip_info(row.path),
                            expected_sha256=row.sha256,
                            expected_size=row.size,
                        )
                    manifest_info = self._zip_info("RELEASE_MANIFEST.json")
                    manifest_info._compresslevel = self._policy.compression_level
                    zf.writestr(manifest_info, manifest_bytes)
                    if resolved_evidence is not None:
                        evidence_info = self._zip_info(RELEASE_EVIDENCE_FILENAME)
                        evidence_info._compresslevel = self._policy.compression_level
                        zf.writestr(evidence_info, resolved_evidence.to_json_bytes())
                        authority = build_release_authority_receipt(frozen_manifest, resolved_evidence)
                        authority_info = self._zip_info(RELEASE_AUTHORITY_FILENAME)
                        authority_info._compresslevel = self._policy.compression_level
                        zf.writestr(authority_info, authority.to_json_bytes())
                sink.flush()
                os.fsync(raw.fileno())
                sha256 = sink.sha256
            durable_replace_file(temp_path, zip_path)
            published = True
        finally:
            if not published:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

        return ReleasePackage(
            str(zip_path),
            sha256,
            frozen_manifest.digest(),
            len(frozen_manifest.files),
            resolved_evidence.digest() if resolved_evidence is not None else None,
        )
