from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from noetrium_platform.foundation.governance.release.runtime.evidence import verify_release_evidence_binding
from noetrium_platform.foundation.governance.release.runtime.authority import load_verified_release_authority
from noetrium_platform.foundation.governance.release.runtime.manifest import build_release_manifest, verify_release_manifest
from noetrium_platform.foundation.governance.release.runtime.package_verification import verify_release_package
from noetrium_platform.foundation.governance.release.runtime.packager import ReleasePackager
from noetrium_platform.foundation.governance.release.runtime.project_metadata import load_project_metadata


@dataclass(frozen=True, slots=True)
class ReleasePipelineResult:
    zip_path: str
    sha256: str
    manifest_digest: str
    evidence_digest: str
    file_count: int


class ReleasePipeline:
    """Orchestrate one exact release from a small number of frozen snapshots."""

    def __init__(self) -> None:
        pass

    def build(self, root: Path) -> ReleasePipelineResult:
        root = Path(root).resolve()
        expected_manifest, evidence, _authority = load_verified_release_authority(root)

        # Snapshot 1: exact bytes before expensive quality analysis.  Pass this
        # snapshot through manifest verification instead of re-hashing per layer.
        before = build_release_manifest(
            root,
            platform_code_version=expected_manifest.platform_code_version,
            python_requires=expected_manifest.python_requires,
        )
        errors = list(verify_release_manifest(root, expected_manifest, actual_manifest=before))
        if evidence.release_manifest_digest != expected_manifest.digest():
            errors.append("release evidence does not bind RELEASE_MANIFEST.json")
        if errors:
            raise RuntimeError("; ".join(errors))

        # Quality/regression execution belongs to evidence generation.  Re-running
        # those analyzers here would duplicate work without adding a new trust
        # boundary: their implementation bytes and outputs are already bound by
        # the exact source manifest and the clean ReleaseEvidence object.
        errors = list(verify_release_evidence_binding(evidence, before))
        if errors:
            raise RuntimeError("; ".join(errors))

        metadata = load_project_metadata(root, allow_unversioned=False)
        output = root.parent / f"{metadata.name}-{metadata.version}-{before.digest()[:12]}-release.zip"
        package = ReleasePackager().build(
            root,
            output,
            evidence=evidence,
            manifest=before,
        )
        verification = verify_release_package(Path(package.zip_path))
        if not verification.clean:
            raise RuntimeError("package verification failed: " + "; ".join(verification.errors))
        return ReleasePipelineResult(
            zip_path=str(package.zip_path),
            sha256=package.sha256,
            manifest_digest=package.manifest_digest,
            evidence_digest=package.evidence_digest or "",
            file_count=package.file_count,
        )
