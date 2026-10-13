from __future__ import annotations
from pathlib import Path
import unittest
from noetrium_platform.foundation.governance.architecture.study_invariants import audit_study_invariants

class StudyCompositionBoundaryV187Tests(unittest.TestCase):
    def test_study_domain_never_imports_runtime_implementations_or_composition(self):
        root=Path(__file__).resolve().parents[1]
        self.assertEqual(audit_study_invariants(root),[])

if __name__=='__main__': unittest.main()
