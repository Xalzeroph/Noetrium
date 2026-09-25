from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.governance.release.api import (
    ReleaseManifest,
    ReleaseVerificationEvidence,
    ReleaseVerificationIntegrityError,
    ReleaseVerificationReport,
)

from .manifest import verify_release_manifest
from .manifest_io import load_release_manifest


class SourceTreeReleaseEvidenceReader:
    """Release-domain adapter that verifies a source-tree release and exports stable evidence."""

    def __init__(self, source_root: Path, release_manifest: ReleaseManifest) -> None:
        self._source_root = Path(source_root)
        self._release_manifest = release_manifest

    def read_release_verification_evidence(self) -> ReleaseVerificationEvidence:
        errors = verify_release_manifest(self._source_root, self._release_manifest)
        if errors:
            raise ReleaseVerificationIntegrityError("release source-tree verification failed")
        return ReleaseVerificationEvidence(
            release_manifest_digest=self._release_manifest.digest(),
            source_tree_sha256=self._release_manifest.source_tree_sha256,
            platform_code_version=self._release_manifest.platform_code_version,
        )


class SourceTreeReleaseVerifier:
    """Concrete source-tree verifier; filesystem/manifest details stay in Release."""

    def __init__(self, source_root: Path, manifest_path: Path) -> None:
        self._source_root = Path(source_root)
        self._manifest_path = Path(manifest_path)

    def verify(self) -> ReleaseVerificationReport:
        manifest = load_release_manifest(self._manifest_path)
        errors = verify_release_manifest(self._source_root, manifest)
        return ReleaseVerificationReport(
            clean=not errors,
            manifest_digest=manifest.digest(),
            source_tree_sha256=manifest.source_tree_sha256,
            file_count=len(manifest.files),
            errors=errors,
        )


__all__ = [
    "ReleaseVerificationIntegrityError",
    "SourceTreeReleaseEvidenceReader",
    "SourceTreeReleaseVerifier",
]
