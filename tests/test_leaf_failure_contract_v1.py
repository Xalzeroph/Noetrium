import unittest
from noetrium_platform.foundation.kernel.kernel.leaf_contract import (
    LeafExecutionError,
    LeafFailureClass,
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

class LeafFailureContractTests(unittest.TestCase):
    def test_programming_failure_is_classified_and_fail_closed(self):
        runtime = SystemLeafRuntimeOwner(CONTRACT).bind(
            lambda op, payload: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        with self.assertRaises(LeafExecutionError) as ctx:
            runtime.execute("x", {})
        self.assertEqual(ctx.exception.receipt.classification, LeafFailureClass.PROGRAMMING)
        self.assertFalse(ctx.exception.receipt.retryable)

    def test_external_failure_is_not_marked_retryable(self):
        runtime = SystemLeafRuntimeOwner(CONTRACT).bind(
            lambda op, payload: (_ for _ in ()).throw(TimeoutError("timeout"))
        )
        with self.assertRaises(LeafExecutionError) as ctx:
            runtime.execute("x", {})
        self.assertEqual(ctx.exception.receipt.effect_certainty, "unknown")

if __name__ == "__main__":
    unittest.main()
