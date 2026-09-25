import tempfile
import unittest
from pathlib import Path

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.composition.operation_forensics import OperationForensicFailureSink
from noetrium_platform.composition.context_action import context_action_failure_classifier_chain
from noetrium_platform.foundation.kernel.kernel import (
    ComponentIdentity,
    ExecutionContext,
    OperationExecutor,
    OperationRequest,
    canonical_digest,
)


class OperationForensicsV103Tests(unittest.TestCase):
    def _request(self, operation_type: str, component_id: str):
        ident=ComponentIdentity(component_id,"impl","1","1","g")
        payload={"x":1}
        ctx=ExecutionContext("run","trace","span",operation_id="op",component_id=component_id)
        return OperationRequest(
            "op", "invocation:test-operation-forensics", operation_type, ctx, ident, ident, payload, "v1", canonical_digest(payload),
            idempotency_key="logical-op-key",
        )

    def test_method_recall_failure_is_durable_and_taxonomy_bound(self):
        with tempfile.TemporaryDirectory() as td:
            with ForensicStore(Path(td)) as store:
                sink=OperationForensicFailureSink(store, classifier=context_action_failure_classifier_chain())
                def fail(request): raise ValueError("planner selected invalid node")
                result=OperationExecutor(sink).execute(self._request("method.recall","method.sem"),fail)
                self.assertTrue(result.failure_id)
                self.assertEqual(store.failures.verify()[0],1)
                rows=store.failures.verified_payloads_after(0).payloads
                failure=rows[0]
                self.assertEqual(failure["failure_domain"],"METHOD")
                self.assertEqual(failure["failure_code"],"SERVING_FAILURE")
                self.assertEqual(failure["operation_type"],"method.recall")
                self.assertEqual(failure["operation_payload_digest"], canonical_digest({"x": 1}))
                self.assertEqual(failure["operation_idempotency_key"], "logical-op-key")

    def test_environment_action_exception_is_conservatively_effect_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            with ForensicStore(Path(td)) as store:
                sink=OperationForensicFailureSink(store, classifier=context_action_failure_classifier_chain())
                def fail(request): raise TimeoutError("bridge timeout")
                OperationExecutor(sink).execute(self._request("environment.act","environment.mc"),fail)
                failure=store.failures.verified_payloads_after(0).payloads[0]
                self.assertEqual(failure["failure_code"],"EFFECT_UNKNOWN")
                self.assertEqual(failure["effect_certainty"],"effect_unknown")
                self.assertEqual(failure["recommended_recovery"],"reconcile_effect")


if __name__ == "__main__":
    unittest.main()
