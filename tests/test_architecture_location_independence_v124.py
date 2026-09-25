from pathlib import Path
import tempfile
import unittest

from noetrium_platform.foundation.governance.architecture import build_architecture_report, build_optimization_report
from noetrium_platform.foundation.governance.providers import RepositorySourceTree


class ArchitectureLocationIndependenceV124Tests(unittest.TestCase):
    def _tree(self, root: Path) -> None:
        package = root / "noetrium_platform" / "sample"
        package.mkdir(parents=True)
        (root / "noetrium_platform" / "__init__.py").write_text("", encoding="utf-8")
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "a.py").write_text("def f(x):\n    return x + 1\n", encoding="utf-8")

    def test_architecture_digest_does_not_bind_absolute_checkout_path(self):
        with tempfile.TemporaryDirectory() as left, tempfile.TemporaryDirectory() as right:
            left_root, right_root = Path(left), Path(right)
            self._tree(left_root); self._tree(right_root)
            left_report = build_architecture_report(left_root, source_index=RepositorySourceTree(left_root).index())
            right_report = build_architecture_report(right_root, source_index=RepositorySourceTree(right_root).index())
            self.assertNotEqual(left_report.source_root, right_report.source_root)
            self.assertEqual(left_report.report_sha256, right_report.report_sha256)

    def test_optimization_digest_does_not_bind_absolute_checkout_path(self):
        with tempfile.TemporaryDirectory() as left, tempfile.TemporaryDirectory() as right:
            left_root, right_root = Path(left), Path(right)
            self._tree(left_root); self._tree(right_root)
            self.assertEqual(
                build_optimization_report(left_root).report_sha256,
                build_optimization_report(right_root).report_sha256,
            )


if __name__ == "__main__":
    unittest.main()
