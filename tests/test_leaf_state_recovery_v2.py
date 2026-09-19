from pathlib import Path
import tempfile
import unittest

from noetrium_platform.capabilities.environment.specification.schema.composition import compose
from noetrium_platform.foundation.kernel.kernel.leaf_contract import LeafExecutionError


class LeafStateRecoveryTests(unittest.TestCase):
    def test_generic_leaf_cannot_manufacture_checkpoint_authority(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(
                LeafExecutionError,
                "canonical authority port",
            ):
                compose(lambda op, payload: {"ok": True}, Path(td) / "state.json")

    def test_stateless_leaf_binding_remains_available(self):
        runtime = compose(lambda op, payload: {"operation": op, "value": payload["value"]})
        result = runtime.execute("project", {"value": 7})
        self.assertEqual(result.output, {"operation": "project", "value": 7})


if __name__ == "__main__":
    unittest.main()
