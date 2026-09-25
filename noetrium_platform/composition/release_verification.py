from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from noetrium_platform.foundation.governance.release.runtime.authority import (
    ReleaseAuthorityMismatch,
    load_verified_release_authority,
)
from noetrium_platform.foundation.governance.release.runtime.evidence import (
    verify_release_evidence_binding,
)
from noetrium_platform.foundation.governance.release.runtime.manifest import (
    build_release_manifest,
    verify_release_manifest,
)
from noetrium_platform.foundation.governance.release.runtime.verification import SourceTreeReleaseVerifier
from noetrium_platform.foundation.governance.release.api import ReleaseVerificationReport, ReleaseVerifierPort


@dataclass(frozen=True, slots=True)
class PersistedReleaseVerificationReport:
    """Cheap verification result for one already-generated release authority."""

    clean: bool
    manifest_digest: str
    evidence_digest: str
    authority_digest: str
    source_tree_sha256: str
    file_count: int
    errors: tuple[str, ...]


def build_source_tree_release_verifier(root: Path, manifest_path: Path) -> ReleaseVerifierPort:
    return SourceTreeReleaseVerifier(root, manifest_path)


def verify_source_tree_release(root: Path, manifest_path: Path) -> ReleaseVerificationReport:
    return build_source_tree_release_verifier(root, manifest_path).verify()


def verify_persisted_release_authority(root: Path) -> PersistedReleaseVerificationReport:
    """Verify persisted evidence without re-running release analyzers."""

    root = Path(root).resolve()
    manifest_digest = ""
    evidence_digest = ""
    authority_digest = ""
    source_tree_sha256 = ""
    file_count = 0
    errors: list[str] = []
    try:
        expected_manifest, evidence, authority = load_verified_release_authority(root)
        actual_manifest = build_release_manifest(
            root,
            platform_code_version=expected_manifest.platform_code_version,
            python_requires=expected_manifest.python_requires,
        )
        errors.extend(
            verify_release_manifest(
                root,
                expected_manifest,
                actual_manifest=actual_manifest,
            )
        )
        errors.extend(verify_release_evidence_binding(evidence, actual_manifest))
        manifest_digest = actual_manifest.digest()
        evidence_digest = evidence.digest()
        authority_digest = authority.digest()
        source_tree_sha256 = actual_manifest.source_tree_sha256
        file_count = len(actual_manifest.files)
    except (ReleaseAuthorityMismatch, OSError, TypeError, ValueError) as exc:
        errors.append(str(exc) or type(exc).__name__)

    return PersistedReleaseVerificationReport(
        clean=not errors,
        manifest_digest=manifest_digest,
        evidence_digest=evidence_digest,
        authority_digest=authority_digest,
        source_tree_sha256=source_tree_sha256,
        file_count=file_count,
        errors=tuple(errors),
    )


__all__ = [
    "PersistedReleaseVerificationReport",
    "build_source_tree_release_verifier",
    "verify_persisted_release_authority",
    "verify_source_tree_release",
]
