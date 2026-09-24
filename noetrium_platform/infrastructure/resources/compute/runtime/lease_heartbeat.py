from __future__ import annotations

from threading import Lock

from noetrium_platform.foundation.kernel.concurrency.api import (
    HeartbeatSchedulerPort,
    HeartbeatSpec,
    ScheduledTaskHandlePort,
    TaskContextPort,
    TaskGroupPort,
)
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeAllocation,
    ComputeLeaseGuardPort,
    ComputeLeasePolicy,
    ComputeSchedulerPort,
    DEFAULT_COMPUTE_LEASE_POLICY,
)


class ComputeLeaseHeartbeatError(RuntimeError):
    """A compute reservation renewal guard lost authority or failed to stop cleanly."""


class ComputeLeaseHeartbeatGuard:
    """Structured periodic renewal for durable compute reservations."""

    def __init__(
        self,
        *,
        scheduler: ComputeSchedulerPort,
        allocation_rows: tuple[ComputeAllocation, ...],
        task_group: TaskGroupPort,
        heartbeat_scheduler: HeartbeatSchedulerPort,
        lane_id: str,
        lane_capacity: int | None = None,
        policy: ComputeLeasePolicy = DEFAULT_COMPUTE_LEASE_POLICY,
    ) -> None:
        if (
            not allocation_rows
            or any(type(row) is not ComputeAllocation for row in allocation_rows)
        ):
            raise ValueError(
                "compute lease heartbeat requires typed allocation generations"
            )
        allocation_ids = tuple(row.allocation_id for row in allocation_rows)
        if len(set(allocation_ids)) != len(allocation_ids):
            raise ValueError("compute lease heartbeat requires unique allocation ids")
        if not lane_id.strip():
            raise ValueError("compute lease heartbeat lane_id required")
        if lane_capacity is not None and lane_capacity <= 0:
            raise ValueError("compute lease heartbeat lane capacity must be positive")
        self._scheduler = scheduler
        self._allocation_rows = allocation_rows
        self._task_group = task_group
        self._heartbeat_scheduler = heartbeat_scheduler
        self._lane_id = lane_id
        self._lane_capacity = lane_capacity
        self._policy = policy
        self._lock = Lock()
        self._scheduled: ScheduledTaskHandlePort | None = None
        self._closing = False
        self._closed = False

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise ComputeLeaseHeartbeatError("compute lease heartbeat is closed")
            if self._closing:
                raise ComputeLeaseHeartbeatError("compute lease heartbeat is closing")
            if self._scheduled is not None:
                return
            self._scheduled = self._heartbeat_scheduler.register(
                self._task_group.group_id,
                HeartbeatSpec(
                    heartbeat_id="compute-lease:" + ",".join(
                        row.allocation_id for row in self._allocation_rows
                    ),
                    lane_id=self._lane_id,
                    interval_seconds=self._policy.renewal_interval_seconds,
                    initial_delay_seconds=self._policy.renewal_interval_seconds,
                    lane_capacity=self._lane_capacity,
                ),
                self._renew_once,
            )

    def _renew_once(self, context: TaskContextPort) -> None:
        context.checkpoint()
        with self._lock:
            expected = self._allocation_rows
        renewed = self._scheduler.renew_many(
            expected,
            ttl_seconds=self._policy.ttl_seconds,
        )
        with self._lock:
            self._allocation_rows = renewed
        context.checkpoint()

    def assert_healthy(self) -> None:
        with self._lock:
            scheduled = self._scheduled
        if scheduled is None:
            return
        try:
            scheduled.assert_healthy()
            self._task_group.assert_healthy()
        except BaseException as exc:
            raise ComputeLeaseHeartbeatError(
                f"compute lease heartbeat failed: {type(exc).__name__}: {exc}"
            ) from exc

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closing = True
            scheduled = self._scheduled
        if scheduled is not None:
            # Teardown cancels future renewal authority. Historical heartbeat
            # failure remains observable through assert_healthy()/task-group
            # evidence, but must not permanently block exact-generation release.
            # Any already-dispatched renewal is fenced by the allocation/lease
            # generation and therefore cannot mutate a replacement generation.
            scheduled.cancel()
        with self._lock:
            self._closed = True
            self._closing = False


class ComputeLeaseHeartbeatFactory:
    """Bind compute lease renewals to one shared structured-concurrency authority."""

    def __init__(
        self,
        *,
        scheduler: ComputeSchedulerPort,
        task_group: TaskGroupPort,
        heartbeat_scheduler: HeartbeatSchedulerPort,
        lane_id: str,
        lane_capacity: int | None = None,
        policy: ComputeLeasePolicy = DEFAULT_COMPUTE_LEASE_POLICY,
    ) -> None:
        self._scheduler = scheduler
        self._task_group = task_group
        self._heartbeat_scheduler = heartbeat_scheduler
        self._lane_id = lane_id
        self._lane_capacity = lane_capacity
        self._policy = policy

    @property
    def policy(self) -> ComputeLeasePolicy:
        return self._policy

    def create(
        self,
        allocations: tuple[ComputeAllocation, ...],
    ) -> ComputeLeaseGuardPort:
        return ComputeLeaseHeartbeatGuard(
            scheduler=self._scheduler,
            allocation_rows=allocations,
            task_group=self._task_group,
            heartbeat_scheduler=self._heartbeat_scheduler,
            lane_id=self._lane_id,
            lane_capacity=self._lane_capacity,
            policy=self._policy,
        )


__all__ = ["ComputeLeaseHeartbeatError", "ComputeLeaseHeartbeatFactory", "ComputeLeaseHeartbeatGuard"]
