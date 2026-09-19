from __future__ import annotations

from threading import Lock

from noetrium_platform.foundation.kernel.concurrency.api import (
    HeartbeatSchedulerPort,
    HeartbeatSpec,
    ScheduledTaskHandlePort,
    TaskContextPort,
    TaskGroupPort,
)
from noetrium_platform.infrastructure.resources.allocation.api import (
    DEFAULT_ENDPOINT_LEASE_POLICY,
    EndpointAllocationPort,
    EndpointLeaseGuardFactoryPort,
    EndpointLeaseGuardPort,
    EndpointLeasePolicy,
)


class EndpointLeaseHeartbeatError(RuntimeError):
    """An endpoint lease renewal guard lost its authority or could not stop cleanly."""


class EndpointLeaseHeartbeatGuard(EndpointLeaseGuardPort):
    """Periodic durable renewal owned by one structured task group.

    The task group owns both periodic scheduling and the shared serial writer
    lane.  A guard therefore owns no thread, timer, or executor directly. Slow
    durable renewals create backpressure because the task-group scheduler never
    overlaps two invocations of the same periodic task.
    """

    def __init__(
        self,
        *,
        allocations: EndpointAllocationPort,
        allocation_ids: tuple[str, ...],
        task_group: TaskGroupPort,
        heartbeat_scheduler: HeartbeatSchedulerPort,
        lane_id: str,
        lane_capacity: int | None = None,
        policy: EndpointLeasePolicy = DEFAULT_ENDPOINT_LEASE_POLICY,
    ) -> None:
        if not allocation_ids:
            raise ValueError("endpoint lease heartbeat requires allocation ids")
        if len(set(allocation_ids)) != len(allocation_ids):
            raise ValueError("endpoint lease heartbeat allocation ids must be unique")
        lane_id = str(lane_id).strip()
        if not lane_id:
            raise ValueError("endpoint lease heartbeat lane_id required")
        if lane_capacity is not None and lane_capacity <= 0:
            raise ValueError("endpoint lease heartbeat lane capacity must be positive")
        self._allocations = allocations
        self._allocation_ids = allocation_ids
        self._task_group = task_group
        self._heartbeat_scheduler = heartbeat_scheduler
        self._lane_id = lane_id
        self._lane_capacity = lane_capacity
        self._policy = policy
        self._state_lock = Lock()
        self._scheduled: ScheduledTaskHandlePort | None = None
        self._closed = False

    def start(self) -> None:
        with self._state_lock:
            if self._closed:
                raise EndpointLeaseHeartbeatError("endpoint lease heartbeat is closed")
            if self._scheduled is not None:
                return
            heartbeat_id = "endpoint-lease:" + ",".join(self._allocation_ids)
            self._scheduled = self._heartbeat_scheduler.register(
                self._task_group.group_id,
                HeartbeatSpec(
                    heartbeat_id=heartbeat_id,
                    lane_id=self._lane_id,
                    interval_seconds=self._policy.renewal_interval_seconds,
                    initial_delay_seconds=self._policy.renewal_interval_seconds,
                    lane_capacity=self._lane_capacity,
                ),
                self._renew_once,
            )

    def _renew_once(self, context: TaskContextPort) -> None:
        context.checkpoint()
        self._allocations.renew_many(
            self._allocation_ids,
            ttl_seconds=self._policy.ttl_seconds,
        )
        context.checkpoint()

    def assert_healthy(self) -> None:
        with self._state_lock:
            scheduled = self._scheduled
        if scheduled is None:
            return
        try:
            scheduled.assert_healthy()
            self._task_group.assert_healthy()
        except BaseException as exc:
            raise EndpointLeaseHeartbeatError(
                f"endpoint lease heartbeat failed: {type(exc).__name__}: {exc}"
            ) from exc

    def close(self) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            scheduled = self._scheduled
        if scheduled is not None:
            scheduled.cancel()
        self.assert_healthy()


class EndpointLeaseHeartbeatFactory(EndpointLeaseGuardFactoryPort):
    def __init__(
        self,
        *,
        allocations: EndpointAllocationPort,
        task_group: TaskGroupPort,
        heartbeat_scheduler: HeartbeatSchedulerPort,
        lane_id: str,
        lane_capacity: int | None = None,
        policy: EndpointLeasePolicy = DEFAULT_ENDPOINT_LEASE_POLICY,
    ) -> None:
        self._allocations = allocations
        self._task_group = task_group
        self._heartbeat_scheduler = heartbeat_scheduler
        self._lane_id = lane_id
        self._lane_capacity = lane_capacity
        self._policy = policy

    def create(self, allocation_ids: tuple[str, ...]) -> EndpointLeaseHeartbeatGuard:
        return EndpointLeaseHeartbeatGuard(
            allocations=self._allocations,
            allocation_ids=allocation_ids,
            task_group=self._task_group,
            heartbeat_scheduler=self._heartbeat_scheduler,
            lane_id=self._lane_id,
            lane_capacity=self._lane_capacity,
            policy=self._policy,
        )


__all__ = [
    "EndpointLeaseHeartbeatError",
    "EndpointLeaseHeartbeatFactory",
    "EndpointLeaseHeartbeatGuard",
]
