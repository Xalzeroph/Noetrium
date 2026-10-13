from __future__ import annotations

from noetrium_platform.composition.diagnostic_degradation import (
    ForensicDiagnosticDegradationSink,
)
from noetrium_platform.evidence.observability.logging.context.api import DiagnosticAddress
from noetrium_platform.evidence.observability.logging.record.api import LogLevel, LogRecord
from noetrium_platform.evidence.observability.logging.storage.runtime.codec import (
    decode_log_record,
    encode_log_record,
)
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    GraphExecutionCoordinate,
    current_execution_context,
    execution_context_from_payload,
    execution_context_payload,
    execution_context_scope,
)
from noetrium_platform.foundation.kernel.record_plane import event_record
from tests._concurrency_support import OwnedForensicStore


def coordinate() -> GraphExecutionCoordinate:
    return GraphExecutionCoordinate(
        research_revision_digest="a" * 64,
        execution_id="execution-1",
        cut_id="b" * 64,
        graph_path=("research-root", "paper", "experiment"),
        graph_node_id="research-root::paper::experiment",
        attempt_id="attempt-7",
        generation=3,
        authority_epoch=11,
    )


def context() -> ExecutionContext:
    return ExecutionContext(
        run_id="c" * 64,
        trace_id="trace-1",
        span_id="span-1",
        task_id="attempt-7",
        component_id="research-root::paper::experiment",
        graph_coordinate=coordinate(),
    )


def test_graph_coordinate_round_trips_with_execution_context_and_scope() -> None:
    original = context()
    restored = execution_context_from_payload(execution_context_payload(original))
    assert restored == original
    assert restored.graph_coordinate == coordinate()
    assert current_execution_context() is None
    with execution_context_scope(original):
        assert current_execution_context() == original
    assert current_execution_context() is None


def test_structured_log_preserves_graph_coordinate() -> None:
    record = LogRecord(
        log_id="log-1",
        created_at=1.0,
        level=LogLevel.ERROR,
        logger="test",
        event="failed",
        message="diagnostic",
        address=DiagnosticAddress(
            scope_path=(PLATFORM_SCOPE,),
            component_id="component",
            trace_id="trace-1",
            span_id="span-1",
            graph_coordinate=coordinate(),
        ),
    )
    restored = decode_log_record(encode_log_record(record))
    assert restored == record
    assert restored.address.graph_coordinate == coordinate()


def test_forensics_indexes_graph_node_and_degradation_without_changing_truth(tmp_path) -> None:
    store = OwnedForensicStore(tmp_path / "forensics")
    try:
        ctx = context()
        store.append_event(event_record("event-primary", "PRIMARY", ctx, "component"))
        sink = ForensicDiagnosticDegradationSink(store)
        degradation_id = sink.record(
            ctx,
            subsystem="test.observer",
            stage="publish",
            exc=RuntimeError("observer failed"),
            correlation_refs=("receipt-1",),
        )
        store.flush_projections()

        records = store.index.for_graph_node(
            "research-root::paper::experiment",
            limit=20,
        )
        assert {row.object_id for row in records} == {
            "event-primary",
            f"event_{degradation_id}",
        }
        for row in records:
            assert row.graph_attempt_id == "attempt-7"
            assert row.graph_generation == 3
            assert row.research_execution_id == "execution-1"
            assert row.research_revision_digest == "a" * 64

        degradation = store.index.locate(f"event_{degradation_id}")
        assert degradation is not None
        payload = degradation.to_payload()
        assert payload["event_type"] == "OBSERVABILITY_DEGRADED"
        assert payload["payload"]["error_type"] == "builtins.RuntimeError"
    finally:
        store.close()
