from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from noetrium_platform.foundation.governance.release.api import ReleaseQualityEvidence
from noetrium_platform.foundation.governance.release.runtime.evidence import build_release_evidence
from noetrium_platform.foundation.governance.release.runtime.authority import publish_release_authority
from noetrium_platform.foundation.governance.release.runtime.manifest import build_release_manifest
from noetrium_platform.foundation.governance.release.runtime.pipeline import ReleasePipeline


def _tree(root: Path) -> None:
    (root / "noetrium_platform").mkdir(parents=True)
    (root / "noetrium_platform" / "__init__.py").write_text("", encoding="utf-8")
    (root / "noetrium_platform" / "x.py").write_text("x=1\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname="release-fixture"\nversion="1.2.3"\nrequires-python=">=3.11"\n',
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


def _write_authorities(root: Path) -> None:
    manifest = build_release_manifest(root)
    evidence = build_release_evidence(
        root,
        quality=_quality(),
        regression_tests_collected=1,
        regression_tests_passed=1,
        regression_tests_skipped=0,
        regression_shard_count=1,
        regression_test_inventory_sha256="c" * 64,
        regression_runtime_sha256="d" * 64,
        regression_plan_sha256="e" * 64,
        manifest=manifest,
    )
    publish_release_authority(root, manifest, evidence)


def test_pipeline_does_not_rerun_quality_during_packaging(monkeypatch) -> None:
    # Packaging consumes already-generated clean evidence.  Static analyzers must
    # not execute a second time at this stage.
    import noetrium_platform.composition.release_quality as quality_module

    def forbidden(*_args, **_kwargs):
        raise AssertionError("quality analyzer must not run during packaging")

    monkeypatch.setattr(quality_module, "build_release_quality_evidence", forbidden)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "src"
        root.mkdir()
        _tree(root)
        _write_authorities(root)
        result = ReleasePipeline().build(root)
        assert Path(result.zip_path).is_file()
        assert len(result.sha256) == 64


def test_pipeline_packages_unchanged_frozen_source() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "src"
        root.mkdir()
        _tree(root)
        _write_authorities(root)
        result = ReleasePipeline().build(root)
        assert Path(result.zip_path).is_file()
        assert len(result.sha256) == 64
