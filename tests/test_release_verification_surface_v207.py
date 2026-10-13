from __future__ import annotations

from pathlib import Path
import tempfile

from noetrium_platform.composition.release_verification import verify_persisted_release_authority
from noetrium_platform.foundation.governance.release.api import ReleaseQualityEvidence
from noetrium_platform.foundation.governance.release.runtime.authority import publish_release_authority
from noetrium_platform.foundation.governance.release.runtime.evidence import build_release_evidence
from noetrium_platform.foundation.governance.release.runtime.manifest import build_release_manifest


def _tree(root: Path) -> None:
    (root / "noetrium_platform").mkdir(parents=True)
    (root / "noetrium_platform" / "__init__.py").write_text("", encoding="utf-8")
    (root / "noetrium_platform" / "x.py").write_text("x = 1\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname="x"\nversion="1.2.3"\nrequires-python=">=3.11"\n',
        encoding="utf-8",
    )


def _quality() -> ReleaseQualityEvidence:
    return ReleaseQualityEvidence(
        architecture_report_sha256="a" * 64,
        architecture_clean=True,
        no_degradation_findings=0,
        silent_failure_findings=0,
        algorithm_source_digest="b" * 64,
        algorithm_clean=True,
        algorithm_blockers=0,
        concurrency_source_digest="c" * 64,
        concurrency_clean=True,
        concurrency_blockers=0,
        performance_source_digest="d" * 64,
        performance_clean=True,
        performance_blockers=0,
    )


def _publish(root: Path, *, tests: int = 1) -> tuple[str, str]:
    manifest = build_release_manifest(root)
    evidence = build_release_evidence(
        root,
        quality=_quality(),
        regression_tests_collected=tests,
        regression_tests_passed=tests,
        regression_tests_skipped=0,
        regression_shard_count=1,
        regression_test_inventory_sha256="e" * 64,
        regression_runtime_sha256="f" * 64,
        regression_plan_sha256="0" * 64,
        manifest=manifest,
    )
    publish_release_authority(root, manifest, evidence)
    return manifest.digest(), evidence.digest()


def test_persisted_release_verification_reuses_clean_evidence() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _tree(root)
        manifest_digest, evidence_digest = _publish(root, tests=3)

        report = verify_persisted_release_authority(root)

        assert report.clean
        assert report.manifest_digest == manifest_digest
        assert report.evidence_digest == evidence_digest
        assert report.authority_digest


def test_persisted_release_verification_rejects_source_drift() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _tree(root)
        _publish(root)
        (root / "noetrium_platform" / "x.py").write_text("x = 2\n", encoding="utf-8")

        report = verify_persisted_release_authority(root)

        assert not report.clean
        assert report.errors
