from __future__ import annotations

from pathlib import Path
import unittest

from noetrium_platform.foundation.governance.architecture.runtime_control_invariants import audit_runtime_control_invariants


class RuntimeControlArchitectureV184Tests(unittest.TestCase):
    def test_control_policy_transition_store_boundaries_are_hard(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(audit_runtime_control_invariants(root), [])


if __name__ == "__main__": unittest.main()
