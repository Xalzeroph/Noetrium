from pathlib import Path
import tempfile
import unittest
from noetrium_platform.foundation.governance.quality import scan_no_degradation
from noetrium_platform.foundation.governance.quality.degradation_paths import is_excluded_path

class NoDegradationV21Tests(unittest.TestCase):
    def test_detects_explicit_runtime_degradation_api(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'bad.py').write_text('fallback_model = "small"\n')
            findings=scan_no_degradation(root); self.assertEqual(findings[0].identifier,'fallback_model')
    def test_does_not_match_comments_or_descriptive_fallback_word(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'ok.py').write_text('# no fallback should exist\nreason = "fallback is forbidden"\n')
            self.assertEqual(scan_no_degradation(root),())
if __name__=='__main__': unittest.main()


def test_runtime_state_directories_are_outside_the_source_audit(tmp_path):
    for dirname in (".local", ".pytest_cache", ".server-state"):
        target = tmp_path / dirname
        target.mkdir(parents=True, exist_ok=True)
        (target / "state.json").write_text('{"fallback_model": "unsafe"}', encoding="utf-8")
    assert scan_no_degradation(tmp_path) == ()


def test_degradation_vocabulary_contract_is_not_self_scanned():
    assert is_excluded_path(
        Path("noetrium_platform/foundation/governance/quality/api/contracts.py")
    )
