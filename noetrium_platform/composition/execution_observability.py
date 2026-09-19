from __future__ import annotations

from noetrium_platform.research.execution.admission.api import AdmissionTopologySnapshot
from noetrium_platform.evidence.observability.projection.api import (
    ExecutionAdmissionScopeFact,
    ExecutionCapacityFacts,
    ExecutionGroupFact,
    SerialMailboxFact,
)
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyTopologySnapshot, TaskState


def build_execution_capacity_facts(
    *,
    admission: AdmissionTopologySnapshot,
    concurrency: ConcurrencyTopologySnapshot,
) -> ExecutionCapacityFacts:
    """Adapt execution authorities into an observability-owned immutable read model."""

    scopes: list[ExecutionAdmissionScopeFact] = [
        ExecutionAdmissionScopeFact(
            scope="global",
            identity="global",
            max_in_flight=admission.max_total_in_flight,
            in_flight=admission.in_flight,
            waiting=admission.waiting,
        )
    ]
    scopes.extend(
        ExecutionAdmissionScopeFact("group", row.group_id, admission.max_in_flight_per_group, row.in_flight, row.waiting)
        for row in admission.groups
    )
    scopes.extend(
        ExecutionAdmissionScopeFact("tenant", row.tenant_id, row.max_in_flight, row.in_flight, row.waiting)
        for row in admission.tenants
    )
    scopes.extend(
        ExecutionAdmissionScopeFact(
            "resource",
            f"{row.tenant_id or '*'}:{row.resource_id}",
            row.max_in_flight,
            row.in_flight,
            row.waiting,
        )
        for row in admission.resources
    )
    scopes.extend(
        ExecutionAdmissionScopeFact("lane", row.lane_kind.value, row.max_in_flight, row.in_flight, row.waiting)
        for row in admission.lanes
    )

    admission_by_group = {row.group_id: row for row in admission.groups}
    groups: list[ExecutionGroupFact] = []
    for group in concurrency.groups:
        counts = {state: 0 for state in TaskState}
        for task in group.tasks:
            counts[task.state] += 1
        identity = admission_by_group.get(group.group_id)
        groups.append(ExecutionGroupFact(
            group_id=group.group_id,
            tenant_id=identity.tenant_id if identity else None,
            resource_id=identity.resource_id if identity else None,
            cancelled=group.cancelled,
            closing=group.closing,
            closed=group.closed,
            converged=group.converged,
            task_total=len(group.tasks),
            task_pending=counts.get(TaskState.PENDING, 0),
            task_running=counts.get(TaskState.RUNNING, 0),
            task_succeeded=counts.get(TaskState.SUCCEEDED, 0),
            task_failed=counts.get(TaskState.FAILED, 0),
            task_cancelled=counts.get(TaskState.CANCELLED, 0),
        ))

    mailboxes = tuple(
        SerialMailboxFact(
            lane_id=row.lane_id,
            owner_group_id=row.owner_group_id,
            capacity=row.capacity,
            closed=row.closed,
            queued_work_items=row.queued_work_items,
            running=row.running,
            logical_outstanding=row.logical_outstanding,
            accepted_work_items_total=row.accepted_work_items_total,
            completed_work_items_total=row.completed_work_items_total,
            failed_work_items_total=row.failed_work_items_total,
            coalesced_submissions_total=row.coalesced_submissions_total,
            mailbox_full_events_total=row.mailbox_full_events_total,
            max_queue_depth=row.max_queue_depth,
        )
        for row in concurrency.serial_lanes
    )
    return ExecutionCapacityFacts(
        closing=concurrency.closing,
        closed=concurrency.closed,
        converged=concurrency.converged,
        shutdown_failure_type=concurrency.shutdown_failure_type,
        admitted_total=admission.admitted_total,
        rejected_total=admission.rejected_total,
        cancelled_total=admission.cancelled_total,
        timed_out_total=admission.timed_out_total,
        queued_total=admission.queued_total,
        cumulative_queue_wait_seconds=admission.cumulative_queue_wait_seconds,
        max_queue_wait_seconds=admission.max_queue_wait_seconds,
        oldest_wait_seconds=admission.oldest_wait_seconds,
        admission_scopes=tuple(scopes),
        groups=tuple(groups),
        serial_mailboxes=mailboxes,
        active_heartbeats=sum(1 for row in concurrency.heartbeats if row.active),
        failed_heartbeats=sum(1 for row in concurrency.heartbeats if row.failure_type is not None),
    )


__all__ = ["build_execution_capacity_facts"]
