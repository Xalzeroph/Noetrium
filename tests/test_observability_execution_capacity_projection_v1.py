from __future__ import annotations

import unittest

from noetrium_platform.research.execution.admission.api import (
    AdmissionTopologySnapshot,
    GroupAdmissionSnapshot,
    LaneAdmissionSnapshot,
    ResourceAdmissionSnapshot,
    TenantAdmissionSnapshot,
)
from noetrium_platform.evidence.observability.diagnostic.snapshot.runtime import (
    project_execution_capacity_diagnostic,
)
from noetrium_platform.evidence.observability.telemetry.metric.composition import build_default_registry
from noetrium_platform.evidence.observability.telemetry.metric.runtime import project_execution_capacity_metrics
from noetrium_platform.composition.execution_observability import build_execution_capacity_facts
from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyTopologySnapshot,
    ExecutionLaneKind,
    HeartbeatTopologySnapshot,
    SerialLaneTopologySnapshot,
    TaskFailurePolicy,
    TaskFailureScope,
    TaskGroupTopologySnapshot,
    TaskState,
    TaskTopologySnapshot,
)


def _source_snapshots() -> tuple[AdmissionTopologySnapshot, ConcurrencyTopologySnapshot]:
    admission = AdmissionTopologySnapshot(
        max_total_in_flight=8,
        max_in_flight_per_group=4,
        max_in_flight_per_tenant=6,
        max_in_flight_per_resource=3,
        in_flight=3,
        waiting=2,
        closed=False,
        admitted_total=21,
        rejected_total=2,
        cancelled_total=1,
        timed_out_total=3,
        queued_total=12,
        cumulative_queue_wait_seconds=4.5,
        max_queue_wait_seconds=1.5,
        oldest_wait_seconds=0.75,
        groups=(GroupAdmissionSnapshot("g1", "tenant-a", "gpu-0", 2, 1),),
        tenants=(TenantAdmissionSnapshot("tenant-a", 6, 2, 1),),
        resources=(ResourceAdmissionSnapshot("tenant-a", "gpu-0", 3, 2, 1),),
        lanes=(LaneAdmissionSnapshot(ExecutionLaneKind.SERIAL, 4, 1, 1),),
    )
    tasks = (
        TaskTopologySnapshot(
            "g1", "task-running", ExecutionLaneKind.SERIAL, "writer", TaskState.RUNNING,
            False, None, None, TaskFailureScope.GROUP,
        ),
        TaskTopologySnapshot(
            "g1", "task-ok", ExecutionLaneKind.SERIAL, "writer", TaskState.SUCCEEDED,
            True, None, None, TaskFailureScope.CALLER,
        ),
    )
    concurrency = ConcurrencyTopologySnapshot(
        closing=False,
        closed=False,
        converged=False,
        shutdown_failure_type=None,
        groups=(TaskGroupTopologySnapshot(
            group_id="g1",
            failure_policy=TaskFailurePolicy.FAIL_FAST,
            deadline_monotonic=None,
            cancelled=False,
            closing=False,
            closed=False,
            converged=False,
            cancellation_reason=None,
            tasks=tasks,
        ),),
        serial_lanes=(SerialLaneTopologySnapshot(
            lane_id="writer",
            owner_group_id="g1",
            capacity=4,
            closed=False,
            queued_work_items=2,
            running=True,
            scheduled=True,
            coalesced_keys=1,
            logical_outstanding=3,
            accepted_work_items_total=9,
            completed_work_items_total=6,
            failed_work_items_total=1,
            coalesced_submissions_total=4,
            mailbox_full_events_total=2,
            max_queue_depth=3,
        ),),
        heartbeats=(
            HeartbeatTopologySnapshot("hb-ok", "g1", "writer", 5.0, True, None),
            HeartbeatTopologySnapshot("hb-failed", "g1", "writer", 5.0, False, "RuntimeError"),
        ),
    )
    return admission, concurrency


class ExecutionCapacityProjectionTests(unittest.TestCase):
    def test_composition_adapts_source_authorities_into_observability_read_model(self) -> None:
        admission, concurrency = _source_snapshots()
        facts = build_execution_capacity_facts(admission=admission, concurrency=concurrency)

        self.assertEqual(facts.admitted_total, 21)
        self.assertEqual(facts.oldest_wait_seconds, 0.75)
        self.assertEqual(facts.active_heartbeats, 1)
        self.assertEqual(facts.failed_heartbeats, 1)
        self.assertEqual(facts.groups[0].tenant_id, "tenant-a")
        self.assertEqual(facts.groups[0].task_running, 1)
        self.assertEqual(facts.groups[0].task_succeeded, 1)
        self.assertEqual(facts.serial_mailboxes[0].queued_work_items, 2)
        self.assertEqual(
            {(row.scope, row.identity) for row in facts.admission_scopes},
            {
                ("global", "global"),
                ("group", "g1"),
                ("tenant", "tenant-a"),
                ("resource", "tenant-a:gpu-0"),
                ("lane", "serial"),
            },
        )

    def test_telemetry_projects_only_metric_semantics_from_read_model(self) -> None:
        admission, concurrency = _source_snapshots()
        facts = build_execution_capacity_facts(admission=admission, concurrency=concurrency)
        rows = project_execution_capacity_metrics(facts, timestamp=123.0)
        registry = build_default_registry()

        by_key = {(row.metric, dict(row.dimensions).get("scope"), dict(row.dimensions).get("id")): row for row in rows}
        self.assertEqual(by_key[("execution.admission.inflight", "global", "global")].value, 3.0)
        mailbox = next(row for row in rows if row.metric == "execution.serial.mailbox.fill")
        self.assertEqual(mailbox.value, 0.5)
        self.assertEqual(mailbox.timestamp, 123.0)
        for row in rows:
            registry.validate_observation(row.metric, row.value, dict(row.dimensions))

    def test_diagnostic_projects_operator_view_without_source_authority_imports(self) -> None:
        admission, concurrency = _source_snapshots()
        facts = build_execution_capacity_facts(admission=admission, concurrency=concurrency)
        snapshot = project_execution_capacity_diagnostic(facts)

        global_pressure = next(row for row in snapshot.pressure if row.scope == "global")
        self.assertEqual(global_pressure.utilization_ratio, 3 / 8)
        self.assertEqual(snapshot.groups[0].task_total, 2)
        self.assertEqual(snapshot.serial_mailboxes[0].fill_ratio, 0.5)
        self.assertEqual(snapshot.serial_mailboxes[0].max_fill_ratio, 0.75)
        self.assertEqual(snapshot.serial_mailboxes[0].coalesced_submissions_total, 4)
        self.assertEqual(snapshot.failed_heartbeats, 1)


if __name__ == "__main__":
    unittest.main()
