from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AdmissionPressureDiagnostic:
    scope: str
    identity: str
    max_in_flight: int | None
    in_flight: int
    waiting: int
    utilization_ratio: float | None


@dataclass(frozen=True, slots=True)
class GroupExecutionDiagnostic:
    group_id: str
    tenant_id: str | None
    resource_id: str | None
    cancelled: bool
    closing: bool
    closed: bool
    converged: bool
    task_total: int
    task_pending: int
    task_running: int
    task_succeeded: int
    task_failed: int
    task_cancelled: int


@dataclass(frozen=True, slots=True)
class SerialMailboxDiagnostic:
    lane_id: str
    owner_group_id: str
    capacity: int
    queued_work_items: int
    running: bool
    logical_outstanding: int
    fill_ratio: float
    max_fill_ratio: float
    coalesced_submissions_total: int
    mailbox_full_events_total: int
    failed_work_items_total: int


@dataclass(frozen=True, slots=True)
class ExecutionCapacityDiagnosticSnapshot:
    closing: bool
    closed: bool
    converged: bool
    shutdown_failure_type: str | None
    oldest_wait_seconds: float
    admitted_total: int
    rejected_total: int
    cancelled_total: int
    timed_out_total: int
    queued_total: int
    cumulative_queue_wait_seconds: float
    max_queue_wait_seconds: float
    active_heartbeats: int
    failed_heartbeats: int
    pressure: tuple[AdmissionPressureDiagnostic, ...]
    groups: tuple[GroupExecutionDiagnostic, ...]
    serial_mailboxes: tuple[SerialMailboxDiagnostic, ...]


__all__ = [
    "AdmissionPressureDiagnostic",
    "ExecutionCapacityDiagnosticSnapshot",
    "GroupExecutionDiagnostic",
    "SerialMailboxDiagnostic",
]
