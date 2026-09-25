from __future__ import annotations

import unittest

from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, ExecutionContext, OperationExecutor, OperationFailure, OperationRequest, canonical_digest


class OperationExceptionChainV117Tests(unittest.TestCase):
    def request(self):
        c=ComponentIdentity("caller","caller","1","1","g")
        t=ComponentIdentity("target","target","1","1","g")
        ctx=ExecutionContext(run_id="r",trace_id="t",span_id="s")
        payload={"x":1}
        return OperationRequest("op","invocation:test-exception-chain","target.work",ctx,c,t,payload,"v1",canonical_digest(payload))

    def test_original_exception_is_chained_but_not_canonicalized(self):
        executor=OperationExecutor(); request=self.request()
        original=ValueError("deep cause")
        result=executor.execute(request,lambda _request: (_ for _ in ()).throw(original))
        self.assertIs(result.cause,original)
        # Transient exception objects must not contaminate deterministic result identity.
        digest=canonical_digest(result)
        self.assertEqual(len(digest),64)
        with self.assertRaises(OperationFailure) as raised:
            executor.require_success(result)
        self.assertIs(raised.exception.__cause__,original)

    def test_transient_cause_does_not_change_canonical_result_digest(self):
        executor=OperationExecutor(); request=self.request()
        a=executor.execute(request,lambda _request: (_ for _ in ()).throw(ValueError("a")))
        b=executor.execute(request,lambda _request: (_ for _ in ()).throw(ValueError("b")))
        # Raw exception messages are process-local/forensic detail, not operation truth.
        # The stable kernel result therefore depends on exception taxonomy, not message text.
        self.assertEqual(canonical_digest(a),canonical_digest(b))


if __name__ == "__main__": unittest.main()
