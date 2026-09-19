from pathlib import Path
import tempfile
import unittest
import zipfile

from noetrium_platform.composition.release_quality import build_release_quality_evidence
from noetrium_platform.foundation.governance.providers import RepositorySourceTree
from noetrium_platform.foundation.governance.release.runtime.evidence import build_release_evidence
from noetrium_platform.foundation.governance.release.runtime.manifest import build_release_manifest
from noetrium_platform.foundation.governance.release.runtime.packager import ReleasePackager
from noetrium_platform.foundation.governance.release.runtime.package_verification import verify_release_package


class ReleasePackageSelfVerificationV190Tests(unittest.TestCase):
    def _tree(self, root: Path) -> None:
        (root / "noetrium_platform").mkdir(parents=True)
        (root / "noetrium_platform" / "__init__.py").write_text("", encoding="utf-8")
        (root / "noetrium_platform" / "x.py").write_text("x=1\n", encoding="utf-8")
        (root / "pyproject.toml").write_text(
            '[project]\nname="x"\nversion="1.2.3"\nrequires-python=">=3.11"\n',
            encoding="utf-8",
        )

    def test_official_package_verifies_every_member_against_frozen_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "src"; root.mkdir(); self._tree(root)
            manifest = build_release_manifest(root)
            evidence = build_release_evidence(
                root,
                quality=build_release_quality_evidence(root, source_index=RepositorySourceTree(root).index()),
                regression_tests_collected=1,
                regression_tests_passed=1,
                regression_tests_skipped=0,
                regression_shard_count=1,
                regression_test_inventory_sha256="1" * 64,
                regression_runtime_sha256="2" * 64,
                regression_plan_sha256="3" * 64,
                manifest=manifest,
            )
            package = ReleasePackager().build(root, Path(td) / "release.zip", evidence=evidence)
            report = verify_release_package(Path(package.zip_path))
            self.assertTrue(report.clean, report.errors)
            self.assertEqual(report.manifest_digest, manifest.digest())
            self.assertEqual(report.evidence_digest, evidence.digest())

    def test_tampered_package_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "src"; root.mkdir(); self._tree(root)
            manifest = build_release_manifest(root)
            evidence = build_release_evidence(
                root,
                quality=build_release_quality_evidence(root, source_index=RepositorySourceTree(root).index()),
                regression_tests_collected=1,
                regression_tests_passed=1,
                regression_tests_skipped=0,
                regression_shard_count=1,
                regression_test_inventory_sha256="1" * 64,
                regression_runtime_sha256="2" * 64,
                regression_plan_sha256="3" * 64,
                manifest=manifest,
            )
            path = Path(td) / "release.zip"
            ReleasePackager().build(root, path, evidence=evidence)
            with zipfile.ZipFile(path, "a") as zf:
                zf.writestr("noetrium_platform/x.py", b"x=999\n")
            report = verify_release_package(path)
            self.assertFalse(report.clean)
            self.assertTrue(any("duplicate ZIP member" in row or "package hash drift" in row for row in report.errors))


    def test_packaging_source_drift_does_not_replace_existing_official_zip(self):
        from noetrium_platform.foundation.governance.release.runtime.evidence import ReleaseEvidenceMismatch
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "src"; root.mkdir(); self._tree(root)
            manifest = build_release_manifest(root)
            output = Path(td) / "release.zip"
            output.write_bytes(b"previous-good-package")
            (root / "noetrium_platform" / "x.py").write_text("x=2\n", encoding="utf-8")
            with self.assertRaises(ReleaseEvidenceMismatch):
                ReleasePackager().build(root, output, manifest=manifest)
            self.assertEqual(output.read_bytes(), b"previous-good-package")

    def test_package_verifier_rejects_path_traversal_member(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.zip"
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr("../escape", b"x")
                zf.writestr("RELEASE_MANIFEST.json", b"{}")
                zf.writestr("RELEASE_EVIDENCE.json", b"{}")
            report = verify_release_package(path)
            self.assertFalse(report.clean)
            self.assertTrue(any("unsafe ZIP member" in row for row in report.errors))

    def test_legacy_package_snapshot_manifests_are_not_release_authorities(self):
        root = Path(__file__).resolve().parents[1]
        self.assertFalse((root / "PACKAGE_CONTENTS.sha256").exists())
        self.assertFalse((root / "PACKAGE_METADATA.json").exists())


if __name__ == "__main__":
    unittest.main()
