from __future__ import annotations

from pathlib import Path
import tempfile

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.composition.operation_forensics import OperationForensicFailureSink
from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, ExecutionContext, OperationExecutor, OperationStatus
from noetrium_platform.research.execution.workflow.runtime import KernelOperationDispatcher


def _dispatch(executor: OperationExecutor, operation_type: str, *, idempotency_key: str | None, called: list[str]):
    identity = ComponentIdentity("component.x", "x", "1", "1", "g")
    return KernelOperationDispatcher(executor).dispatch(
        root_context=ExecutionContext("run", "trace", "span"),
        operation_id="op",
        operation_type=operation_type,
        target=identity,
        payload={"x": 1},
        payload_schema="v1",
        idempotency_key=idempotency_key,
        handler=lambda request: called.append("executed") or "ok",
    )


def test_protected_mutation_fails_inside_operation_boundary_before_handler_executes():
    called: list[str] = []
    result = _dispatch(OperationExecutor(), "method.task_completed", idempotency_key=None, called=called)
    assert result.status is OperationStatus.FAILED
    assert called == []
    assert result.diagnostics["exception_type"] == "OperationSemanticPolicyViolation"


def test_policy_violation_is_forensically_classified_without_executing_side_effect():
    with tempfile.TemporaryDirectory() as td, ForensicStore(Path(td)) as store:
        called: list[str] = []
        executor = OperationExecutor(OperationForensicFailureSink(store))
        result = _dispatch(executor, "environment.act", idempotency_key=None, called=called)
        assert result.status is OperationStatus.FAILED
        assert called == []
        failure = store.failures.verified_payloads_after(0).payloads[0]
        assert failure["failure_code"] == "OPERATION_SEMANTIC_POLICY_VIOLATION"
        assert failure["operation_payload_digest"]
        assert failure["operation_idempotency_key"] is None


def test_protected_mutation_accepts_stable_key_and_read_operation_does_not_require_one():
    called: list[str] = []
    protected = _dispatch(OperationExecutor(), "method.task_completed", idempotency_key="cycle:run:dc", called=called)
    read_only = _dispatch(OperationExecutor(), "environment.observe", idempotency_key=None, called=called)
    assert protected.output == "ok"
    assert read_only.output == "ok"
    assert called == ["executed", "executed"]
