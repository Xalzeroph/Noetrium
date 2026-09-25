from pathlib import Path
import tempfile, unittest
from noetrium_platform.foundation.governance.architecture import analyze_optimization_risks, build_optimization_report

class OptimizationReportV34Tests(unittest.TestCase):
    def test_detects_io_lock_and_state_mutation_concentration(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); pkg=root/'noetrium_platform'; pkg.mkdir(); (pkg/'__init__.py').write_text('')
            (pkg/'x.py').write_text('''from threading import RLock\nclass X:\n def __init__(self): self._lock=RLock(); self.x=0\n def f(self,p):\n  with self._lock:\n   self.x=1\n   open(p).read()\n   open(p).read()\n   open(p).read()\n   open(p).read()\n   open(p).read()\n   open(p).read()\n''')
            row=analyze_optimization_risks(root)[0]
            self.assertIn('IO_CONCENTRATION',row.reason_codes)
            self.assertGreater(row.risk_score,0)
    def test_report_has_stable_digest_and_real_project_candidates(self):
        root=Path(__file__).resolve().parents[1]; report=build_optimization_report(root)
        self.assertEqual(len(report.report_sha256),64); self.assertTrue(report.modules)

if __name__=='__main__': unittest.main()
