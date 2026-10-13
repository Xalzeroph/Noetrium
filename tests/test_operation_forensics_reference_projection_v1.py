from __future__ import annotations

from noetrium_platform.composition.operation_forensics import (
    OperationForensicFailureSink,
)
from noetrium_platform.foundation.kernel.kernel import (
    ComponentIdentity,
    ExecutionContext,
    OperationRequest,
    canonical_digest,
)
from noetrium_platform.infrastructure.reliability.failure.api import (
    failure_field,
)


class _AppendOnlyFailureStore:
    def __init__(self) -> None:
        self.failure = None

    def append_failure_once(self, failure):
        self.failure = failure
        return True, None


class _ReferencedFailure(RuntimeError):
    def __init__(self) -> None:
        self.request_refs = ("request-r",)
        self.effect_refs = ("effect-r",)
        self.state_refs = ("state-r",)
        self.evidence_refs = ("evidence-r",)
        self.artifact_refs = ("artifact-r",)
        self.correlation_refs = ("correlation-r",)
        super().__init__("referenced failure")


def test_operation_failure_uses_universal_exception_reference_projection() -> None:
    store = _AppendOnlyFailureStore()
    sink = OperationForensicFailureSink(store)
    caller = ComponentIdentity("caller", "caller", "1", "1", "g")
    target = ComponentIdentity("target", "target", "1", "1", "g")
    context = ExecutionContext("run", "trace", "span")
    payload = {"x": 1}
    request = OperationRequest(
        "op",
        "invocation",
        "unit.test",
        context,
        caller,
        target,
        payload,
        "v1",
        canonical_digest(payload),
    )

    sink.record(request, _ReferencedFailure())

    failure = store.failure
    assert failure is not None
    assert failure_field(failure, "request_refs") == ("request-r",)
    assert failure_field(failure, "effect_refs") == ("effect-r",)
    assert failure_field(failure, "state_refs") == ("state-r",)
    assert failure_field(failure, "evidence_refs") == ("evidence-r",)
    assert failure_field(failure, "artifact_refs") == ("artifact-r",)
    assert failure_field(failure, "correlation_refs") == ("correlation-r",)
