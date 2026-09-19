from pathlib import Path
import json
import tempfile
import unittest
import zipfile

from noetrium_platform.foundation.governance.release.runtime.evidence import (
    ReleaseEvidenceMismatch,
    build_release_evidence,
    verify_release_evidence,
    write_release_evidence,
)
from noetrium_platform.foundation.governance.release.runtime.manifest import build_release_manifest
from noetrium_platform.composition.release_quality import build_release_quality_evidence
from noetrium_platform.foundation.governance.providers import RepositorySourceTree
from noetrium_platform.foundation.governance.release.runtime.packager import ReleasePackager


class ReleaseEvidenceV125Tests(unittest.TestCase):
    def _tree(self, root: Path) -> None:
        (root / "noetrium_platform").mkdir(parents=True)
        (root / "noetrium_platform" / "__init__.py").write_text("", encoding="utf-8")
        (root / "noetrium_platform" / "x.py").write_text("x=1\n", encoding="utf-8")
        (root / "pyproject.toml").write_text(
            '[project]\nname="x"\nversion="1.2.3"\nrequires-python=">=3.11"\n',
            encoding="utf-8",
        )

    def test_evidence_is_derived_and_does_not_hash_itself(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); self._tree(root)
            before = build_release_manifest(root)
            evidence = build_release_evidence(root, quality=build_release_quality_evidence(root, source_index=RepositorySourceTree(root).index()), regression_tests_collected=7, regression_tests_passed=7, regression_tests_skipped=0, regression_shard_count=1, regression_test_inventory_sha256="1"*64, regression_runtime_sha256="2"*64, regression_plan_sha256="3"*64)
            write_release_evidence(root / "RELEASE_EVIDENCE.json", evidence)
            after = build_release_manifest(root)
            self.assertEqual(before.digest(), after.digest())
            self.assertEqual(verify_release_evidence(root, evidence, quality=build_release_quality_evidence(root, source_index=RepositorySourceTree(root).index()), observed_tests_passed=7), ())

    def test_packager_includes_only_matching_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "src"; root.mkdir(); self._tree(root)
            evidence = build_release_evidence(root, quality=build_release_quality_evidence(root, source_index=RepositorySourceTree(root).index()), regression_tests_collected=7, regression_tests_passed=7, regression_tests_skipped=0, regression_shard_count=1, regression_test_inventory_sha256="1"*64, regression_runtime_sha256="2"*64, regression_plan_sha256="3"*64)
            write_release_evidence(root / "RELEASE_EVIDENCE.json", evidence)
            package = ReleasePackager().build(root, Path(td) / "x.zip")
            self.assertEqual(package.evidence_digest, evidence.digest())
            with zipfile.ZipFile(package.zip_path) as zf:
                payload = json.loads(zf.read("RELEASE_EVIDENCE.json"))
            self.assertEqual(payload["release_manifest_digest"], evidence.release_manifest_digest)

    def test_stale_evidence_blocks_packaging(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "src"; root.mkdir(); self._tree(root)
            evidence = build_release_evidence(root, quality=build_release_quality_evidence(root, source_index=RepositorySourceTree(root).index()), regression_tests_collected=7, regression_tests_passed=7, regression_tests_skipped=0, regression_shard_count=1, regression_test_inventory_sha256="1"*64, regression_runtime_sha256="2"*64, regression_plan_sha256="3"*64)
            write_release_evidence(root / "RELEASE_EVIDENCE.json", evidence)
            (root / "noetrium_platform" / "x.py").write_text("x=2\n", encoding="utf-8")
            with self.assertRaises(ReleaseEvidenceMismatch):
                ReleasePackager().build(root, Path(td) / "x.zip")


if __name__ == "__main__":
    unittest.main()
