from pathlib import Path
import re
import unittest


class ReleaseDocsSingleTruthV128Tests(unittest.TestCase):
    def test_readme_is_current_release_navigation_not_history(self):
        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/architecture/SYSTEM_ARCHITECTURE.md", readme)
        self.assertIn("docs/architecture/RUNTIME_AND_DEPLOYMENT.md", readme)
        self.assertNotIn("docs/status/CURRENT_DEVELOPMENT_BASELINE.md", readme)
        self.assertNotIn("docs/history/", readme)

    def test_release_docs_define_one_generated_frozen_truth(self):
        root = Path(__file__).resolve().parents[1]
        release_doc = (root / "docs" / "governance" / "RELEASE_SYSTEM.md").read_text(encoding="utf-8")
        for token in ("RELEASE_MANIFEST.json", "RELEASE_EVIDENCE.json", "RELEASE_AUTHORITY.json"):
            self.assertIn(token, release_doc)
        self.assertIn("verify_release_evidence.py", release_doc)
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
            if not base.exists():
                continue
            for path in base.rglob("*.py"):
                if version in path.read_text(encoding="utf-8"):
                    hits.append(path.relative_to(root).as_posix())
        self.assertEqual(hits, [], f"project version duplicated in source: {hits}")


if __name__ == "__main__":
    unittest.main()
