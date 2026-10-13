from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.foundation.kernel.record_plane import event_record
from noetrium_platform.infrastructure.reliability.forensics.providers import index_projection as projection_module
from noetrium_platform.infrastructure.reliability.forensics.providers.index_projection import event_projection
from noetrium_platform.infrastructure.reliability.forensics.runtime import write_lanes as write_lanes_module


class ForensicsProjectionHotPathTests(unittest.TestCase):
    @staticmethod
    def _context() -> ExecutionContext:
        return ExecutionContext(
            run_id="run-1",
            trace_id="trace-1",
            span_id="span-1",
            task_id="task-1",
        )

    def test_event_projection_materializes_document_and_json_once(self) -> None:
        event = event_record(
            "event-1",
            "PHASE_COMPLETED",
            self._context(),
            "component",
            payload={"value": 1},
            timestamp=10.0,
        )
        document = projection_module.event_document
        dumps = json.dumps
        with mock.patch.object(
            projection_module,
            "event_document",
            wraps=document,
        ) as document_call, mock.patch.object(
            projection_module.json,
            "dumps",
            wraps=dumps,
        ) as json_call:
            projected = event_projection(event)

        self.assertEqual(document_call.call_count, 1)
        self.assertEqual(json_call.call_count, 1)
        self.assertIsNone(projected.operation_invocation)

    def test_authoritative_append_reuses_document_for_projection(self) -> None:
        event = event_record(
            "event-reuse",
            "PHASE_COMPLETED",
            self._context(),
            "component",
            payload={"value": 2},
            timestamp=12.0,
        )
        document = write_lanes_module.event_document
        with tempfile.TemporaryDirectory() as td, mock.patch.object(
            write_lanes_module,
            "event_document",
            wraps=document,
        ) as document_call:
            with ForensicStore(Path(td)) as store:
                store.append_event(event)
                store.flush_projections()
                located = store.index.locate("event-reuse")

        self.assertEqual(document_call.call_count, 1)
        self.assertIsNotNone(located)
        assert located is not None
        self.assertEqual(located.object_id, "event-reuse")

    def test_operation_projection_preserves_started_and_terminal_state(self) -> None:
        payload = {
            "operation_id": "logical-op",
            "operation_invocation_id": "inv-1",
            "operation_type": "environment.act_prepared",
            "caller_component_id": "workflow.context_action",
            "target_component_id": "environment.test",
            "payload_schema": "action.v1",
            "payload_digest": "digest-in",
        }
        started = event_record(
            "event-started",
            "OPERATION_STARTED",
            self._context(),
            "environment.test",
            payload=payload,
            timestamp=10.0,
        )
        terminal_payload = dict(payload)
        terminal_payload.update({"status": "succeeded", "failure_id": None})
        terminal = event_record(
            "event-terminal",
            "OPERATION_SUCCEEDED",
            self._context(),
            "environment.test",
            payload=terminal_payload,
            timestamp=11.0,
        )

        with tempfile.TemporaryDirectory() as td:
            with ForensicStore(Path(td)) as store:
                store.append_event(started)
                store.append_event(terminal)
                store.flush_projections()
                invocation = store.index.operation_invocation("inv-1")

        self.assertIsNotNone(invocation)
        assert invocation is not None
        self.assertEqual(invocation.started_event_id, "event-started")
        self.assertEqual(invocation.terminal_event_id, "event-terminal")
        self.assertEqual(invocation.status, "succeeded")
        self.assertEqual(invocation.started_at, 10.0)
        self.assertEqual(invocation.terminal_at, 11.0)


if __name__ == "__main__":
    unittest.main()
