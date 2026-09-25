from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from noetrium_platform.foundation.kernel.concurrency.api import Deadline, ExecutionLaneKind, TaskFailureScope, TaskState
from noetrium_platform.foundation.kernel.concurrency.api.ports import ScheduledTaskHandlePort
from .cancellation import _CancellationState, _DeadlineOwner

_TERMINAL_STATES = frozenset({TaskState.SUCCEEDED, TaskState.FAILED, TaskState.CANCELLED})

@dataclass(slots=True)
class _TaskRecord:
    task_id: str
    lane_kind: ExecutionLaneKind
    lane_id: str | None
    deadline: Deadline | None
    deadline_owner: _DeadlineOwner
    failure_scope: TaskFailureScope
    cancellation: _CancellationState = field(default_factory=_CancellationState)
    state: TaskState = TaskState.PENDING
    failure: BaseException | None = None
    raw_handle: Any | None = None
    deadline_handle: ScheduledTaskHandlePort | None = None



@dataclass(slots=True)
class _RecurringRecord:
    task_id: str
    lane_id: str
    deadline: Deadline | None
    deadline_owner: _DeadlineOwner
    cancellation: _CancellationState = field(default_factory=_CancellationState)
    state: TaskState = TaskState.PENDING
    failure: BaseException | None = None
    current: Any | None = None
    cancelled: bool = False
    deadline_handle: ScheduledTaskHandlePort | None = None
    timer_handle: ScheduledTaskHandlePort | None = None



__all__ = ["_RecurringRecord", "_TaskRecord", "_TERMINAL_STATES"]
