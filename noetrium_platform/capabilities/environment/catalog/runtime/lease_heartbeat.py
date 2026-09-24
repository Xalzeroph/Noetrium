from __future__ import annotations

from threading import Lock

from noetrium_platform.foundation.kernel.concurrency.api import (
    HeartbeatSchedulerPort,
    HeartbeatSpec,
    ScheduledTaskHandlePort,
    TaskContextPort,
    TaskGroupPort,
)

from .lease_authority import (
    DEFAULT_ENVIRONMENT_INSTANCE_LEASE_POLICY,
    EnvironmentInstanceLeaseAuthority,
    EnvironmentInstanceLeaseHandle,
    EnvironmentInstanceLeasePolicy,
)


class EnvironmentInstanceLeaseHeartbeatError(RuntimeError):
    """An environment checkout lease renewal lost authority or failed."""


class EnvironmentInstanceLeaseHeartbeatGuard:
    """Structured periodic renewal for one or more environment generations."""

    def __init__(
        self,
        *,
        authority: EnvironmentInstanceLeaseAuthority,
        handles: tuple[EnvironmentInstanceLeaseHandle, ...],
        task_group: TaskGroupPort,
        heartbeat_scheduler: HeartbeatSchedulerPort,
        lane_id: str,
        lane_capacity: int | None = None,
        policy: EnvironmentInstanceLeasePolicy = DEFAULT_ENVIRONMENT_INSTANCE_LEASE_POLICY,
    ) -> None:
        if not handles:
            raise ValueError("environment lease heartbeat requires handles")
        instance_ids = tuple(handle.instance.instance_id for handle in handles)
        if len(set(instance_ids)) != len(instance_ids):
            raise ValueError("environment lease heartbeat instance ids must be unique")
        if not lane_id.strip():
            raise ValueError("environment lease heartbeat lane_id required")
        if lane_capacity is not None and lane_capacity <= 0:
            raise ValueError("environment lease heartbeat lane capacity must be positive")
        self._authority = authority
        self._handles = handles
        self._task_group = task_group
        self._heartbeat_scheduler = heartbeat_scheduler
        self._lane_id = lane_id
        self._lane_capacity = lane_capacity
        self._policy = policy
        self._lock = Lock()
        self._scheduled: ScheduledTaskHandlePort | None = None
        self._closed = False

    @property
    def handles(self) -> tuple[EnvironmentInstanceLeaseHandle, ...]:
        with self._lock:
            return self._handles

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise EnvironmentInstanceLeaseHeartbeatError(
                    "environment lease heartbeat is closed"
                )
            if self._scheduled is not None:
                return
            instance_ids = tuple(
                handle.instance.instance_id for handle in self._handles
            )
            self._scheduled = self._heartbeat_scheduler.register(
                self._task_group.group_id,
                HeartbeatSpec(
                    heartbeat_id="environment-instance-lease:" + ",".join(instance_ids),
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
            handles = self._handles
        renewed = self._authority.renew_many(handles)
        with self._lock:
            self._handles = renewed
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
            raise EnvironmentInstanceLeaseHeartbeatError(
                f"environment lease heartbeat failed: {type(exc).__name__}: {exc}"
            ) from exc

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            scheduled = self._scheduled
        if scheduled is not None:
            scheduled.cancel()
        self.assert_healthy()


class EnvironmentInstanceLeaseHeartbeatFactory:
    def __init__(
        self,
        *,
        authority: EnvironmentInstanceLeaseAuthority,
        task_group: TaskGroupPort,
        heartbeat_scheduler: HeartbeatSchedulerPort,
        lane_id: str,
        lane_capacity: int | None = None,
        policy: EnvironmentInstanceLeasePolicy = DEFAULT_ENVIRONMENT_INSTANCE_LEASE_POLICY,
    ) -> None:
        self._authority = authority
        self._task_group = task_group
        self._heartbeat_scheduler = heartbeat_scheduler
        self._lane_id = lane_id
        self._lane_capacity = lane_capacity
        self._policy = policy

    @property
    def policy(self) -> EnvironmentInstanceLeasePolicy:
        return self._policy

    def create(
        self,
        handles: tuple[EnvironmentInstanceLeaseHandle, ...],
    ) -> EnvironmentInstanceLeaseHeartbeatGuard:
        return EnvironmentInstanceLeaseHeartbeatGuard(
            authority=self._authority,
            handles=handles,
            task_group=self._task_group,
            heartbeat_scheduler=self._heartbeat_scheduler,
            lane_id=self._lane_id,
            lane_capacity=self._lane_capacity,
            policy=self._policy,
        )


__all__ = [
    "EnvironmentInstanceLeaseHeartbeatError",
    "EnvironmentInstanceLeaseHeartbeatFactory",
    "EnvironmentInstanceLeaseHeartbeatGuard",
]
