from __future__ import annotations

from collections.abc import Callable
from threading import Lock
from typing import Generic, TypeVar

from noetrium_platform.foundation.kernel.concurrency.api import (
    HeartbeatSchedulerPort,
    HeartbeatSpec,
    ScheduledTaskHandlePort,
    TaskContextPort,
    TaskGroupPort,
)

RowT = TypeVar("RowT")
PolicyT = TypeVar("PolicyT")


class LeaseHeartbeatError(RuntimeError):
    """A resource lease renewal loop lost authority or failed."""

class LeaseHeartbeatGuard(Generic[RowT]):
    """Single structured heartbeat state machine for every renewable resource lease."""

    def __init__(
        self,
        *,
        rows: tuple[RowT, ...],
        renew: Callable[[tuple[RowT, ...]], tuple[RowT, ...]],
        row_identity: Callable[[RowT], str],
        heartbeat_namespace: str,
        task_group: TaskGroupPort,
        heartbeat_scheduler: HeartbeatSchedulerPort,
        lane_id: str,
        interval_seconds: float,
        lane_capacity: int | None = None,
    ) -> None:
        if not rows:
            raise ValueError("lease heartbeat requires at least one row")
        identities = tuple(row_identity(row) for row in rows)
        if any(type(value) is not str or not value.strip() for value in identities):
            raise ValueError("lease heartbeat row identities must be non-empty text")
        if len(set(identities)) != len(identities):
            raise ValueError("lease heartbeat row identities must be unique")
        if not heartbeat_namespace.strip() or not lane_id.strip():
            raise ValueError("lease heartbeat namespace and lane_id are required")
        if interval_seconds <= 0:
            raise ValueError("lease heartbeat interval must be positive")
        if lane_capacity is not None and lane_capacity <= 0:
            raise ValueError("lease heartbeat lane capacity must be positive")
        self._rows = rows
        self._renew = renew
        self._row_identity = row_identity
        self._heartbeat_namespace = heartbeat_namespace
        self._task_group = task_group
        self._heartbeat_scheduler = heartbeat_scheduler
        self._lane_id = lane_id
        self._interval_seconds = float(interval_seconds)
        self._lane_capacity = lane_capacity
        self._lock = Lock()
        self._scheduled: ScheduledTaskHandlePort | None = None
        self._closing = False
        self._closed = False

    @property
    def handles(self) -> tuple[RowT, ...]:
        with self._lock:
            return self._rows

    @property
    def rows(self) -> tuple[RowT, ...]:
        return self.handles

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise LeaseHeartbeatError("lease heartbeat is closed")
            if self._closing:
                raise LeaseHeartbeatError("lease heartbeat is closing")
            if self._scheduled is not None:
                return
            heartbeat_id = self._heartbeat_namespace + ":" + ",".join(
                self._row_identity(row) for row in self._rows
            )
            self._scheduled = self._heartbeat_scheduler.register(
                self._task_group.group_id,
                HeartbeatSpec(
                    heartbeat_id=heartbeat_id,
                    lane_id=self._lane_id,
                    interval_seconds=self._interval_seconds,
                    initial_delay_seconds=self._interval_seconds,
                    lane_capacity=self._lane_capacity,
                ),
                self._renew_once,
            )

    def _renew_once(self, context: TaskContextPort) -> None:
        context.checkpoint()
        with self._lock:
            expected = self._rows
        renewed = self._renew(expected)
        if type(renewed) is not tuple or len(renewed) != len(expected):
            raise RuntimeError("lease heartbeat renewal cardinality drifted")
        with self._lock:
            self._rows = renewed
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
            raise LeaseHeartbeatError(
                f"lease heartbeat failed: {type(exc).__name__}: {exc}"
            ) from exc

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closing = True
            scheduled = self._scheduled
        if scheduled is not None:
            scheduled.cancel()
        with self._lock:
            self._closed = True
            self._closing = False


class LeaseHeartbeatFactory(Generic[RowT, PolicyT]):
    """Bind one renewal operation to the universal lease-heartbeat machine."""

    def __init__(
        self,
        *,
        renew: Callable[[tuple[RowT, ...]], tuple[RowT, ...]],
        row_identity: Callable[[RowT], str],
        heartbeat_namespace: str,
        task_group: TaskGroupPort,
        heartbeat_scheduler: HeartbeatSchedulerPort,
        lane_id: str,
        interval_seconds: float,
        policy: PolicyT,
        lane_capacity: int | None = None,
    ) -> None:
        self._renew = renew
        self._row_identity = row_identity
        self._heartbeat_namespace = heartbeat_namespace
        self._task_group = task_group
        self._heartbeat_scheduler = heartbeat_scheduler
        self._lane_id = lane_id
        self._interval_seconds = float(interval_seconds)
        self._lane_capacity = lane_capacity
        self._policy = policy

    @property
    def policy(self) -> PolicyT:
        return self._policy

    def create(self, rows: tuple[RowT, ...]) -> LeaseHeartbeatGuard[RowT]:
        return LeaseHeartbeatGuard(
            rows=rows,
            renew=self._renew,
            row_identity=self._row_identity,
            heartbeat_namespace=self._heartbeat_namespace,
            task_group=self._task_group,
            heartbeat_scheduler=self._heartbeat_scheduler,
            lane_id=self._lane_id,
            interval_seconds=self._interval_seconds,
            lane_capacity=self._lane_capacity,
        )


__all__ = ["LeaseHeartbeatError", "LeaseHeartbeatFactory", "LeaseHeartbeatGuard"]
