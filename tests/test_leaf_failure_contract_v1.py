import tempfile, unittest
from pathlib import Path
from noetrium_platform.capabilities.environment.specification.schema.composition import compose
from noetrium_platform.foundation.kernel.kernel.leaf_contract import LeafExecutionError, LeafFailureClass
class LeafFailureContractTests(unittest.TestCase):
 def test_programming_failure_is_classified_and_fail_closed(self):
  runtime=compose(lambda op,payload: (_ for _ in ()).throw(RuntimeError('boom')))
  with self.assertRaises(LeafExecutionError) as ctx: runtime.execute('x',{})
  self.assertEqual(ctx.exception.receipt.classification,LeafFailureClass.PROGRAMMING)
  self.assertFalse(ctx.exception.receipt.retryable)
 def test_external_failure_is_not_marked_retryable(self):
  runtime=compose(lambda op,payload: (_ for _ in ()).throw(TimeoutError('timeout')))
  with self.assertRaises(LeafExecutionError) as ctx: runtime.execute('x',{})
  self.assertEqual(ctx.exception.receipt.effect_certainty,'unknown')
if __name__=='__main__': unittest.main()
