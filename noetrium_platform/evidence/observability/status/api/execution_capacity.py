from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExecutionAdmissionScopeFact:
    scope: str
    identity: str
    max_in_flight: int | None
    in_flight: int
    waiting: int


@dataclass(frozen=True, slots=True)
class ExecutionGroupFact:
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
class SerialMailboxFact:
    lane_id: str
    owner_group_id: str
    capacity: int
    closed: bool
    queued_work_items: int
    running: bool
    logical_outstanding: int
    accepted_work_items_total: int
    completed_work_items_total: int
    failed_work_items_total: int
    coalesced_submissions_total: int
    mailbox_full_events_total: int
    max_queue_depth: int


@dataclass(frozen=True, slots=True)
class ExecutionCapacityFacts:
    closing: bool
    closed: bool
    converged: bool
    shutdown_failure_type: str | None
    admitted_total: int
    rejected_total: int
    cancelled_total: int
    timed_out_total: int
    queued_total: int
    cumulative_queue_wait_seconds: float
    max_queue_wait_seconds: float
    oldest_wait_seconds: float
    admission_scopes: tuple[ExecutionAdmissionScopeFact, ...]
    groups: tuple[ExecutionGroupFact, ...]
    serial_mailboxes: tuple[SerialMailboxFact, ...]
    active_heartbeats: int
    failed_heartbeats: int


__all__ = [
    "ExecutionAdmissionScopeFact",
    "ExecutionCapacityFacts",
    "ExecutionGroupFact",
    "SerialMailboxFact",
]
