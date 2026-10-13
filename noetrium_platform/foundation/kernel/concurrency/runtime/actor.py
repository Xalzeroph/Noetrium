from __future__ import annotations

from threading import Lock
from typing import Any, Callable, TypeVar

from noetrium_platform.foundation.kernel.concurrency.api import (
    Deadline,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskContextPort,
    TaskFailureScope,
    TaskHandlePort,
)

T = TypeVar("T")


class SerialActor:
    """Synchronous façade over one task-group-owned serial execution lane."""

    def __init__(self, group, actor_id: str, *, lane_id: str, capacity: int | None) -> None:
        actor_id = str(actor_id).strip()
        lane_id = str(lane_id).strip()
        if not actor_id:
            raise ValueError("serial actor id required")
        if not lane_id:
            raise ValueError("serial actor lane id required")
        self._group = group
        self._actor_id = actor_id
        self._lane_id = lane_id
        self._capacity = capacity
        self._sequence = 0
        self._sequence_lock = Lock()

    @property
    def actor_id(self) -> str:
        return self._actor_id

    def _next_task_id(self, operation: str) -> str:
        operation = str(operation).strip()
        if not operation:
            raise ValueError("serial actor operation required")
        with self._sequence_lock:
            self._sequence += 1
            sequence = self._sequence
        return f"actor:{self._actor_id}:{sequence}:{operation}"

    def submit(
        self,
        operation: str,
        fn: Callable[..., T],
        /,
        *args: Any,
        deadline: Deadline | None = None,
        **kwargs: Any,
    ) -> TaskHandlePort[T]:
        def invoke(context: TaskContextPort) -> T:
            context.checkpoint()
            result = fn(*args, **kwargs)
            context.checkpoint()
            return result

        return self._group.submit(
            ExecutionSpec(
                task_id=self._next_task_id(operation),
                lane_kind=ExecutionLaneKind.SERIAL,
                lane_id=self._lane_id,
                capacity=self._capacity,
                failure_scope=TaskFailureScope.CALLER,
            ),
            invoke,
            deadline=deadline,
        )

    def call(
        self,
        operation: str,
        fn: Callable[..., T],
        /,
        *args: Any,
        deadline: Deadline | None = None,
        **kwargs: Any,
    ) -> T:
        handle = self.submit(operation, fn, *args, deadline=deadline, **kwargs)
        timeout = None if deadline is None else deadline.remaining_seconds
        return handle.result(timeout=timeout)


__all__ = ["SerialActor"]
