from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Any, Callable

from noetrium_platform.foundation.kernel.concurrency.api import (
    Deadline,
    HeartbeatSpec,
    HeartbeatTopologySnapshot,
    ScheduledTaskHandlePort,
    ScheduledTaskSpec,
)
from .task_group import StructuredTaskGroup


@dataclass(slots=True)
class _HeartbeatRecord:
    owner_group_id: str
    spec: HeartbeatSpec
    handle: ScheduledTaskHandlePort
    cancelled: bool = False


class _HeartbeatHandle(ScheduledTaskHandlePort):
    def __init__(self, scheduler: "UnifiedHeartbeatScheduler", heartbeat_id: str) -> None:
        self._scheduler = scheduler
        self._heartbeat_id = heartbeat_id

    @property
    def task_id(self) -> str:
        return self._heartbeat_id

    def cancel(self) -> None:
        self._scheduler._cancel(self._heartbeat_id)

    def assert_healthy(self) -> None:
        self._scheduler._assert_healthy(self._heartbeat_id)


class UnifiedHeartbeatScheduler:
    """One process-wide heartbeat registry backed by the shared timer authority.

    A heartbeat never owns a thread, timer loop, or executor. Registration is
    routed into the owning structured task group, the runtime-wide heap timer is
    the only clock authority, and durable/effectful work is serialized through an
    explicitly owned SERIAL lane. A slow heartbeat is coalesced rather than
    overlapped, so timer pressure cannot create unbounded renewal fanout.
    """

    def __init__(self, group_resolver: Callable[[str], StructuredTaskGroup]) -> None:
        self._group_resolver = group_resolver
        self._lock = Lock()
        self._seen_ids: set[str] = set()
        self._records: dict[str, _HeartbeatRecord] = {}

    def register(
        self,
        owner_group_id: str,
        spec: HeartbeatSpec,
        fn: Callable[..., Any],
        /,
        *args: Any,
        deadline: Deadline | None = None,
        **kwargs: Any,
    ) -> ScheduledTaskHandlePort:
        heartbeat_id = str(spec.heartbeat_id).strip()
        owner_group_id = str(owner_group_id).strip()
        if not owner_group_id:
            raise ValueError("heartbeat owner group id required")
        with self._lock:
            if heartbeat_id in self._seen_ids:
                raise ValueError(f"heartbeat id already owned for runtime lifetime: {heartbeat_id}")
            self._seen_ids.add(heartbeat_id)
        try:
            group = self._group_resolver(owner_group_id)
            delegate = group._schedule_serial_fixed_delay(
                spec.lane_id,
                ScheduledTaskSpec(
                    task_id=f"heartbeat:{heartbeat_id}",
                    interval_seconds=spec.interval_seconds,
                    initial_delay_seconds=spec.resolved_initial_delay_seconds,
                ),
                fn,
                *args,
                deadline=deadline,
                capacity=spec.lane_capacity,
                **kwargs,
            )
            with self._lock:
                self._records[heartbeat_id] = _HeartbeatRecord(
                    owner_group_id=owner_group_id,
                    spec=spec,
                    handle=delegate,
                )
            return _HeartbeatHandle(self, heartbeat_id)
        except BaseException:
            # Registration did not become owned. An identity that never reached
            # the runtime topology can be retried; successfully registered ids are
            # lifetime-unique and are never silently recycled after cancellation.
            with self._lock:
                self._seen_ids.discard(heartbeat_id)
                self._records.pop(heartbeat_id, None)
            raise

    def _record(self, heartbeat_id: str) -> _HeartbeatRecord:
        with self._lock:
            record = self._records.get(heartbeat_id)
        if record is None:
            raise KeyError(f"heartbeat registration not found: {heartbeat_id}")
        return record

    def _cancel(self, heartbeat_id: str) -> None:
        record = self._record(heartbeat_id)
        record.handle.cancel()
        with self._lock:
            record.cancelled = True

    def _assert_healthy(self, heartbeat_id: str) -> None:
        record = self._record(heartbeat_id)
        record.handle.assert_healthy()

    def snapshot(self) -> tuple[HeartbeatTopologySnapshot, ...]:
        with self._lock:
            records = tuple(self._records.items())
        rows: list[HeartbeatTopologySnapshot] = []
        for heartbeat_id, record in records:
            failure_type: str | None = None
            try:
                record.handle.assert_healthy()
            except BaseException as exc:
                failure_type = type(exc).__name__
            rows.append(
                HeartbeatTopologySnapshot(
                    heartbeat_id=heartbeat_id,
                    owner_group_id=record.owner_group_id,
                    lane_id=record.spec.lane_id,
                    interval_seconds=record.spec.interval_seconds,
                    active=not record.cancelled and failure_type is None,
                    failure_type=failure_type,
                )
            )
        return tuple(sorted(rows, key=lambda item: item.heartbeat_id))


__all__ = ["UnifiedHeartbeatScheduler"]
