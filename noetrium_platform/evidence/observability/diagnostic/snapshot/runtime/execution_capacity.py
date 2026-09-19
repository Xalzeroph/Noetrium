from __future__ import annotations

from noetrium_platform.evidence.observability.diagnostic.snapshot.api import (
    AdmissionPressureDiagnostic,
    ExecutionCapacityDiagnosticSnapshot,
    GroupExecutionDiagnostic,
    SerialMailboxDiagnostic,
)
from noetrium_platform.evidence.observability.projection.api import ExecutionCapacityFacts


def project_execution_capacity_diagnostic(
    facts: ExecutionCapacityFacts,
) -> ExecutionCapacityDiagnosticSnapshot:
    """Build an operator-facing diagnostic view without creating new business truth."""

    pressure = tuple(
        AdmissionPressureDiagnostic(
            scope=row.scope,
            identity=row.identity,
            max_in_flight=row.max_in_flight,
            in_flight=row.in_flight,
            waiting=row.waiting,
            utilization_ratio=(
                min(1.0, row.in_flight / row.max_in_flight)
                if row.max_in_flight
                else None
            ),
        )
        for row in facts.admission_scopes
    )
    groups = tuple(
        GroupExecutionDiagnostic(
            group_id=row.group_id,
            tenant_id=row.tenant_id,
            resource_id=row.resource_id,
            cancelled=row.cancelled,
            closing=row.closing,
            closed=row.closed,
            converged=row.converged,
            task_total=row.task_total,
            task_pending=row.task_pending,
            task_running=row.task_running,
            task_succeeded=row.task_succeeded,
            task_failed=row.task_failed,
            task_cancelled=row.task_cancelled,
        )
        for row in facts.groups
    )
    serial = tuple(
        SerialMailboxDiagnostic(
            lane_id=row.lane_id,
            owner_group_id=row.owner_group_id,
            capacity=row.capacity,
            queued_work_items=row.queued_work_items,
            running=row.running,
            logical_outstanding=row.logical_outstanding,
            fill_ratio=min(1.0, row.queued_work_items / row.capacity) if row.capacity else 0.0,
            max_fill_ratio=min(1.0, row.max_queue_depth / row.capacity) if row.capacity else 0.0,
            coalesced_submissions_total=row.coalesced_submissions_total,
            mailbox_full_events_total=row.mailbox_full_events_total,
            failed_work_items_total=row.failed_work_items_total,
        )
        for row in facts.serial_mailboxes
    )
    return ExecutionCapacityDiagnosticSnapshot(
        closing=facts.closing,
        closed=facts.closed,
        converged=facts.converged,
        shutdown_failure_type=facts.shutdown_failure_type,
        oldest_wait_seconds=facts.oldest_wait_seconds,
        admitted_total=facts.admitted_total,
        rejected_total=facts.rejected_total,
        cancelled_total=facts.cancelled_total,
        timed_out_total=facts.timed_out_total,
        queued_total=facts.queued_total,
        cumulative_queue_wait_seconds=facts.cumulative_queue_wait_seconds,
        max_queue_wait_seconds=facts.max_queue_wait_seconds,
        active_heartbeats=facts.active_heartbeats,
        failed_heartbeats=facts.failed_heartbeats,
        pressure=pressure,
        groups=groups,
        serial_mailboxes=serial,
    )


__all__ = ["project_execution_capacity_diagnostic"]
