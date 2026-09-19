from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile

import pytest

from tests._concurrency_support import OwnedForensicStore as ForensicStore, owned_task_group
from noetrium_platform.infrastructure.reliability.forensics.composition import rebuild_forensic_index
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.evidence.observability.api import EventEnvelope


def _ctx(run_id: str = "run-1") -> ExecutionContext:
    return ExecutionContext(
        run_id=run_id,
        trace_id="trace-1",
        span_id="span-1",
        task_id="task-1",
        decision_cycle_id="dc-1",
    )


def _event(invocation_id: str, event_type: str, *, timestamp: float) -> EventEnvelope:
    terminal = event_type != "OPERATION_STARTED"
    payload: dict[str, object] = {
        "operation_id": "logical-op",
        "operation_invocation_id": invocation_id,
        "operation_type": "environment.act_prepared",
        "caller_component_id": "workflow.context_action",
        "target_component_id": "environment.test",
        "payload_schema": "action.v1",
        "payload_digest": "digest-in",
    }
    if terminal:
        payload.update({"status": event_type.removeprefix("OPERATION_").lower(), "failure_id": None})
    return EventEnvelope(
        event_id=f"event-{invocation_id}-{event_type.lower()}",
        event_type=event_type,
        context=_ctx(),
        component_id="environment.test",
        timestamp=timestamp,
        payload=payload,
    )


def test_started_without_terminal_is_queryable_as_unclosed_invocation() -> None:
    with tempfile.TemporaryDirectory() as td:
        with ForensicStore(Path(td)) as store:
            store.append_event(_event("inv-1", "OPERATION_STARTED", timestamp=10.0))
            store.flush_projections()
            rows = store.index.unclosed_operations(run_id="run-1")
            assert len(rows) == 1
            assert rows[0].invocation_id == "inv-1"
            assert rows[0].operation_type == "environment.act_prepared"
            assert rows[0].target_component_id == "environment.test"
            assert rows[0].started_at == 10.0
            with pytest.raises(TypeError):
                rows[0].payload['event_type'] = 'CORRUPTED'
            with pytest.raises(TypeError):
                rows[0].payload['payload']['operation_id'] = 'changed'
            with pytest.raises(ValueError):
                replace(rows[0], invocation_id='different')


def test_terminal_event_closes_exact_invocation_without_collapsing_logical_retries() -> None:
    with tempfile.TemporaryDirectory() as td:
        with ForensicStore(Path(td)) as store:
            store.append_event(_event("inv-1", "OPERATION_STARTED", timestamp=10.0))
            store.append_event(_event("inv-1", "OPERATION_SUCCEEDED", timestamp=11.0))
            store.append_event(_event("inv-2", "OPERATION_STARTED", timestamp=12.0))
            store.flush_projections()
            rows = store.index.unclosed_operations(run_id="run-1")
            assert tuple(row.invocation_id for row in rows) == ("inv-2",)
            closed = store.index.operation_invocation("inv-1")
            assert closed is not None
            closed_payload = closed.to_payload()
            assert closed_payload["event_type"] == "OPERATION_SUCCEEDED"
            assert closed_payload["payload"]["operation_invocation_id"] == "inv-1"


def test_unclosed_projection_is_rebuildable_from_verified_event_ledger() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        with ForensicStore(root) as store:
            store.append_event(_event("inv-orphan", "OPERATION_STARTED", timestamp=20.0))
            store.flush_projections()
        (root / "index.sqlite3").unlink()
        rebuild_forensic_index(root, task_group=owned_task_group("forensic-rebuild"))
        with ForensicStore(root, read_only=True) as store:
            rows = store.index.unclosed_operations()
            assert tuple(row.invocation_id for row in rows) == ("inv-orphan",)


def test_historical_open_at_query_preserves_temporal_context_after_later_completion() -> None:
    with tempfile.TemporaryDirectory() as td:
        with ForensicStore(Path(td)) as store:
            store.append_event(_event("inv-historical", "OPERATION_STARTED", timestamp=10.0))
            store.append_event(_event("inv-historical", "OPERATION_SUCCEEDED", timestamp=30.0))
            store.flush_projections()
            assert store.index.unclosed_operations(run_id="run-1") == ()
            open_at_failure = store.index.operations_open_at(run_id="run-1", timestamp=20.0)
            assert len(open_at_failure) == 1
            assert open_at_failure[0].invocation_id == "inv-historical"
            assert open_at_failure[0].terminal_at == 30.0
            assert store.index.operations_open_at(run_id="run-1", timestamp=31.0) == ()


def test_operation_query_outputs_preserve_limit_tail_for_output_cardinality_lower_bound() -> None:
    with tempfile.TemporaryDirectory() as td:
        with ForensicStore(Path(td)) as store:
            for index in range(32):
                store.append_event(_event(f"inv-tail-{index:02d}", "OPERATION_STARTED", timestamp=10.0 + index))
            store.flush_projections()

            unclosed = store.index.unclosed_operations(run_id="run-1", limit=32)
            open_at = store.index.operations_open_at(run_id="run-1", timestamp=100.0, limit=32)

            assert len(unclosed) == 32
            assert len(open_at) == 32
            assert unclosed[-1].invocation_id == "inv-tail-00"
            assert open_at[-1].invocation_id == "inv-tail-00"
