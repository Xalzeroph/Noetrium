from pathlib import Path
import tempfile
import unittest

from noetrium_platform.foundation.kernel.kernel.leaf_contract import (
    LeafExecutionError,
    SystemLeafContract,
    SystemLeafRuntimeOwner,
)

CONTRACT = SystemLeafContract(
    system_id="test",
    node="test/leaf",
    package_prefix="noetrium_platform.test.leaf",
    authority_id="test-authority",
    owns="test behavior",
    must_not_own="durable truth",
    api_module="noetrium_platform.test.leaf.api",
    runtime_module="noetrium_platform.test.leaf.runtime",
    provider_module="noetrium_platform.test.leaf.providers",
    composition_module="noetrium_platform.test.leaf.composition",
)

class LeafStateRecoveryTests(unittest.TestCase):
    def test_generic_leaf_cannot_manufacture_checkpoint_authority(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(LeafExecutionError, "canonical authority port"):
                SystemLeafRuntimeOwner(CONTRACT).bind(
                    lambda op, payload: {"ok": True},
                    Path(td) / "state.json",
                )

    def test_stateless_leaf_binding_remains_available(self):
        runtime = SystemLeafRuntimeOwner(CONTRACT).bind(
            lambda op, payload: {"operation": op, "value": payload["value"]}
        )
        result = runtime.execute("project", {"value": 7})
        self.assertEqual(result.output, {"operation": "project", "value": 7})

if __name__ == "__main__":
    unittest.main()
