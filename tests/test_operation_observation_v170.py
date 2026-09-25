from __future__ import annotations

from pathlib import Path
import tempfile

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.composition.operation import build_operation_executor
from noetrium_platform.composition.operation_forensics import OperationForensicFailureSink
from noetrium_platform.foundation.kernel.kernel import (
    ComponentIdentity,
    ExecutionContext,
    FailureRecordReceipt,
    OperationExecutor,
    OperationRequest,
    OperationStatus,
    canonical_digest,
)


def _request(invocation_id: str = "op@test-invocation") -> OperationRequest[dict[str, int]]:
    caller = ComponentIdentity("caller", "caller", "1", "1", "g")
    target = ComponentIdentity("target", "target", "1", "1", "g")
    payload = {"x": 1}
    context = ExecutionContext(
        "run",
        "trace",
        f"span:{invocation_id}",
        operation_id="op",
        component_id=target.component_id,
    )
    return OperationRequest(
        "op",
        invocation_id,
        "target.work",
        context,
        caller,
        target,
        payload,
        "payload.v1",
        canonical_digest(payload),
    )


def test_observation_sink_failure_is_auxiliary_and_does_not_change_success():
    class BrokenObserver:
        observer_id = "test.broken_observer"

        def on_started(self, request):
            del request

        def on_completed(self, request, result):
            del request, result
            raise OSError("observer unavailable")

    result = OperationExecutor(observers=(BrokenObserver(),)).execute(
        _request(), lambda request: {"ok": request.payload["x"]}
    )

    assert result.status is OperationStatus.SUCCEEDED
    assert result.output == {"ok": 1}
    assert len(result.auxiliary_failures) == 1
    auxiliary = result.auxiliary_failures[0]
    assert auxiliary.subsystem == "test.broken_observer"
    assert auxiliary.stage == "operation_completed"
    assert auxiliary.error_type == "OSError"
    assert "observer unavailable" not in repr(auxiliary)


def test_failure_materialization_failure_never_masks_primary_component_exception():
    class BrokenFailureSink:
        def record(self, request, exc):
            raise RuntimeError("forensic backend unavailable")

    original = ValueError("primary scientific failure")
    result = OperationExecutor(BrokenFailureSink()).execute(
        _request(), lambda _: (_ for _ in ()).throw(original)
    )

    assert result.status is OperationStatus.FAILED
    assert result.cause is original
    assert result.failure_id is None
    assert len(result.auxiliary_failures) == 1
    assert result.auxiliary_failures[0].stage == "failure_record"


def test_forensic_lifecycle_has_distinct_operation_and_failure_materialization_events():
    with tempfile.TemporaryDirectory() as td, ForensicStore(Path(td)) as store:
        executor = build_operation_executor(
            failure_sink=OperationForensicFailureSink(store), event_sink=store
        )

        success_request = _request("op@success")
        success = executor.execute(success_request, lambda _: {"ok": True})
        assert success.status is OperationStatus.SUCCEEDED

        failure_request = _request("op@failure")
        failure = executor.execute(
            failure_request,
            lambda _: (_ for _ in ()).throw(OSError("disk")),
        )
        assert failure.status is OperationStatus.FAILED
        assert failure.failure_id

        rows = store.events.verified_payloads_after(0).payloads
        by_type: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            by_type.setdefault(str(row["event_type"]), []).append(row)

        assert len(by_type["OPERATION_STARTED"]) == 2
        assert len(by_type["OPERATION_SUCCEEDED"]) == 1
        assert len(by_type["OPERATION_FAILED"]) == 1
        assert len(by_type["FAILURE_RECORDED"]) == 1

        failed_operation = by_type["OPERATION_FAILED"][0]
        recorded_failure = by_type["FAILURE_RECORDED"][0]
        assert failed_operation["payload"]["operation_invocation_id"] == "op@failure"
        assert failed_operation["payload"]["failure_id"] == failure.failure_id
        assert recorded_failure["payload"]["operation_invocation_id"] == "op@failure"
        assert recorded_failure["payload"]["failure_id"] == failure.failure_id

        failure_row = store.failures.verified_payloads_after(0).payloads[0]
        assert failure_row["operation_invocation_id"] == "op@failure"


def test_completed_observer_failure_gets_its_own_durable_auxiliary_event():
    from noetrium_platform.evidence.observability.api import (
        OperationAuxiliaryFailureEventSink,
        OperationLifecycleObserver,
    )

    class BrokenObserver:
        observer_id = "test.completed_observer"

        def on_started(self, request):
            del request

        def on_completed(self, request, result):
            del request, result
            raise OSError("secondary telemetry unavailable")

    with tempfile.TemporaryDirectory() as td, ForensicStore(Path(td)) as store:
        executor = OperationExecutor(
            observers=(OperationLifecycleObserver(store), BrokenObserver()),
            auxiliary_failure_sink=OperationAuxiliaryFailureEventSink(store),
        )
        result = executor.execute(_request("op@aux-durable"), lambda _: {"ok": True})

        assert result.status is OperationStatus.SUCCEEDED
        assert len(result.auxiliary_failures) == 1
        rows = store.events.verified_payloads_after(0).payloads
        auxiliary = [row for row in rows if row["event_type"] == "OPERATION_AUXILIARY_FAILURE"]
        assert len(auxiliary) == 1
        payload = auxiliary[0]["payload"]
        assert payload["operation_invocation_id"] == "op@aux-durable"
        assert payload["subsystem"] == "test.completed_observer"
        assert payload["stage"] == "operation_completed"
        assert "secondary telemetry unavailable" not in str(payload)


def test_auxiliary_failure_sink_failure_is_itself_auxiliary_and_never_changes_primary_truth():
    class BrokenObserver:
        observer_id = "test.broken_observer"

        def on_started(self, request):
            del request

        def on_completed(self, request, result):
            del request, result
            raise OSError("observer unavailable")

    class BrokenAuxiliarySink:
        def record(self, request, failures):
            del request, failures
            raise RuntimeError("auxiliary ledger unavailable")

    result = OperationExecutor(
        observers=(BrokenObserver(),),
        auxiliary_failure_sink=BrokenAuxiliarySink(),
    ).execute(_request("op@aux-sink-fails"), lambda _: {"ok": True})

    assert result.status is OperationStatus.SUCCEEDED
    assert result.output == {"ok": True}
    assert [row.stage for row in result.auxiliary_failures] == [
        "operation_completed",
        "auxiliary_failure_record",
    ]
    assert result.auxiliary_failures[-1].subsystem == "auxiliary_failure_sink"


def test_authoritative_failure_id_survives_disposable_failure_projection_breakage():
    with tempfile.TemporaryDirectory() as td, ForensicStore(Path(td)) as store:
        failure_lane = store._runtime.failure_lane
        assert failure_lane is not None

        def broken_projection(*args, **kwargs):
            del args, kwargs
            raise RuntimeError("sqlite projection unavailable")

        failure_lane.projector = broken_projection
        executor = build_operation_executor(
            failure_sink=OperationForensicFailureSink(store), event_sink=store
        )
        request = _request("op@failure-projection-degraded")
        result = executor.execute(
            request,
            lambda _: (_ for _ in ()).throw(ValueError("primary failure")),
        )

        assert result.status is OperationStatus.FAILED
        assert result.failure_id is not None
        assert any(row.stage == "failure_projection" for row in result.auxiliary_failures)
        failure_rows = store.failures.verified_payloads_after(0).payloads
        assert any(row["failure_id"] == result.failure_id for row in failure_rows)
        event_rows = store.events.verified_payloads_after(0).payloads
        auxiliary = [row for row in event_rows if row["event_type"] == "OPERATION_AUXILIARY_FAILURE"]
        assert auxiliary
        assert auxiliary[-1]["payload"]["stage"] == "failure_projection"
        assert "sqlite projection unavailable" not in str(auxiliary[-1]["payload"])


def test_auxiliary_failure_never_exposes_credentials_in_transient_message():
    class BrokenObserver:
        observer_id = "test.secret_observer"
        def on_started(self, request): del request
        def on_completed(self, request, result):
            del request, result
            raise RuntimeError("api_key=supersecretvalue Bearer abcdefghijklmnop")

    result = OperationExecutor(observers=(BrokenObserver(),)).execute(
        _request("op@secret-aux"), lambda _: {"ok": True}
    )
    failure = result.auxiliary_failures[0]
    assert "supersecretvalue" not in failure.message
    assert "abcdefghijklmnop" not in failure.message
    assert "REDACTED" in failure.message
