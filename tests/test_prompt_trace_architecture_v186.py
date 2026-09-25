from __future__ import annotations
from pathlib import Path
import unittest
from noetrium_platform.foundation.governance.architecture.prompt_invariants import audit_prompt_invariants

class PromptTraceArchitectureV186Tests(unittest.TestCase):
    def test_prompt_trace_does_not_own_telemetry_backend(self):
        root=Path(__file__).resolve().parents[1]
        self.assertEqual(audit_prompt_invariants(root),[])

if __name__=='__main__': unittest.main()
