from __future__ import annotations
from pathlib import Path
import unittest
from noetrium_platform.foundation.governance.architecture.process_invariants import audit_process_invariants

class ProcessArchitectureV185Tests(unittest.TestCase):
    def test_process_capture_is_neutral_and_service_does_not_import_model_os(self):
        root=Path(__file__).resolve().parents[1]
        self.assertEqual(audit_process_invariants(root),[])

if __name__=='__main__': unittest.main()
