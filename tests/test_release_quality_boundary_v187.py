from __future__ import annotations
from pathlib import Path
import unittest
from noetrium_platform.foundation.governance.architecture.release_invariants import audit_release_invariants

class ReleaseQualityBoundaryV187Tests(unittest.TestCase):
    def test_release_consumes_quality_evidence_instead_of_running_quality_systems(self):
        root=Path(__file__).resolve().parents[1]
        self.assertEqual(audit_release_invariants(root),[])

if __name__=='__main__': unittest.main()
