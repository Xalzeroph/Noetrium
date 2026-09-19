from pathlib import Path
import tempfile

import pytest

from noetrium_platform.foundation.governance.release.api import ReleaseQualityEvidence
from noetrium_platform.foundation.governance.release.runtime.authority import (
    ReleaseAuthorityMismatch,
    load_verified_release_authority,
    publish_release_authority,
)
from noetrium_platform.foundation.governance.release.runtime.evidence import build_release_evidence
from noetrium_platform.foundation.governance.release.runtime.manifest import build_release_manifest


def _quality() -> ReleaseQualityEvidence:
    return ReleaseQualityEvidence("a" * 64, True, 0, 0, "b" * 64, True, 0, "c" * 64, True, 0, "d" * 64, True, 0)


def _tree(root: Path) -> None:
    (root / "noetrium_platform").mkdir()
    (root / "noetrium_platform" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname="x"\nversion="1.0.0"\nrequires-python=">=3.11"\n', encoding="utf-8"
    )


def test_authority_receipt_is_commit_point_for_manifest_evidence_pair() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); _tree(root)
        manifest = build_release_manifest(root)
        evidence = build_release_evidence(
            root, quality=_quality(), regression_tests_collected=1, regression_tests_passed=1,
            regression_tests_skipped=0, regression_shard_count=1,
            regression_test_inventory_sha256="c"*64, regression_runtime_sha256="d"*64,
            regression_plan_sha256="e"*64, manifest=manifest,
        )
        receipt = publish_release_authority(root, manifest, evidence)
        loaded_manifest, loaded_evidence, loaded_receipt = load_verified_release_authority(root)
        assert loaded_manifest.digest() == manifest.digest()
        assert loaded_evidence.digest() == evidence.digest()
        assert loaded_receipt == receipt


def test_mixed_authority_pair_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); _tree(root)
        manifest = build_release_manifest(root)
        evidence = build_release_evidence(
            root, quality=_quality(), regression_tests_collected=1, regression_tests_passed=1,
            regression_tests_skipped=0, regression_shard_count=1,
            regression_test_inventory_sha256="c"*64, regression_runtime_sha256="d"*64,
            regression_plan_sha256="e"*64, manifest=manifest,
        )
        publish_release_authority(root, manifest, evidence)
        payload = (root / "RELEASE_EVIDENCE.json").read_text(encoding="utf-8").replace('"regression_tests_passed": 1', '"regression_tests_passed": 2')
        (root / "RELEASE_EVIDENCE.json").write_text(payload, encoding="utf-8")
        with pytest.raises(ReleaseAuthorityMismatch):
            load_verified_release_authority(root)
