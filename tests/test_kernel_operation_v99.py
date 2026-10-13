import unittest
from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import (
    ComponentIdentity,
    ExecutionContext,
    FailureRecordReceipt,
    OperationExecutor,
    OperationRequest,
    OperationStatus,
    canonical_digest,
)


class KernelOperationV99Tests(unittest.TestCase):
    def _request(self, payload=object()):
        if type(payload) is object:
            payload = {"x": 1}
        ctx = ExecutionContext("run", "trace", "root")
        ident = ComponentIdentity("a", "impl", "1", "1", "g")
        return OperationRequest(
            "op1", "invocation:test-kernel", "test", ctx.child(span_id="child", operation_id="op1", component_id="a"),
            ident, ident, payload, "test.v1", canonical_digest(payload),
        )

    def test_child_context_retains_parent_span(self):
        child = ExecutionContext("run", "trace", "root").child(span_id="child")
        self.assertEqual(child.parent_span_id, "root")
        self.assertEqual(child.span_id, "child")

    def test_executor_converts_success_to_result(self):
        result = OperationExecutor().execute(self._request(), lambda request: {"ok": request.payload["x"]})
        self.assertEqual(result.status, OperationStatus.SUCCEEDED)
        self.assertEqual(result.output, {"ok": 1})
        self.assertEqual(result.output_digest, canonical_digest({"ok": 1}))

    def test_executor_converts_component_exception_without_importing_forensics(self):
        class Sink:
            def __init__(self): self.calls = 0
            def record(self, request, exc): self.calls += 1; return FailureRecordReceipt("failure-1")
        sink = Sink()
        def fail(request): raise OSError("disk")
        result = OperationExecutor(sink).execute(self._request(), fail)
        self.assertEqual(result.status, OperationStatus.FAILED)
        self.assertEqual(result.failure_id, "failure-1")
        self.assertEqual(result.diagnostics["exception_type"], "OSError")
        self.assertEqual(sink.calls, 1)


if __name__ == "__main__":
    unittest.main()
