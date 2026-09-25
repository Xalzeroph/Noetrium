from pathlib import Path
import re
import unittest


class ReleaseDocsSingleTruthV128Tests(unittest.TestCase):
    def test_documents_do_not_claim_a_manual_current_test_baseline(self):
        root = Path(__file__).resolve().parents[1]
        release_doc = (root / "docs" / "governance" / "RELEASE_SYSTEM.md").read_text(encoding="utf-8")
        self.assertNotRegex(release_doc, r"Current\s+\d+[ -]Test Baseline")
        self.assertIn("RELEASE_EVIDENCE.json", release_doc)

    def test_readme_marks_round_count_as_historical(self):
        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text(encoding="utf-8")
        self.assertIn("Historical changes are intentionally kept out of this README", readme)
        self.assertIn("current development truth", readme)
        self.assertIn("docs/status/CURRENT_DEVELOPMENT_BASELINE.md", readme)

    def test_release_docs_define_one_frozen_truth_and_no_legacy_package_manifest(self):
        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text(encoding="utf-8")
        release_doc = (root / "docs" / "governance" / "RELEASE_SYSTEM.md").read_text(encoding="utf-8")
        baseline = (root / "docs" / "status" / "CURRENT_DEVELOPMENT_BASELINE.md").read_text(encoding="utf-8")
        self.assertIn("docs/architecture/", readme)
        for text in (release_doc, baseline):
            self.assertIn("RELEASE_MANIFEST.json", text)
            self.assertIn("RELEASE_EVIDENCE.json", text)
        self.assertIn("verify_release_package.py", release_doc)
        self.assertFalse((root / "PACKAGE_CONTENTS.sha256").exists())
        self.assertFalse((root / "PACKAGE_METADATA.json").exists())

    def test_version_literal_has_single_project_authority(self):
        root = Path(__file__).resolve().parents[1]
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, flags=re.MULTILINE)
        self.assertIsNotNone(match)
        version = match.group(1)
        hits = []
        for base in (root / "noetrium_platform", root / "projects"):
            for path in base.rglob("*.py"):
                if version in path.read_text(encoding="utf-8"):
                    hits.append(path.relative_to(root).as_posix())
        self.assertEqual(hits, [], f"project version duplicated in source: {hits}")


if __name__ == "__main__":
    unittest.main()
