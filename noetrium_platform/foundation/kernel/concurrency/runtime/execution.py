from __future__ import annotations

import time
from typing import Any, Callable, TypeVar

from noetrium_platform.foundation.kernel.concurrency.api import (
    SerialMailboxPolicy,
    SerialMailboxRejected,
    Deadline,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskCancelled,
)
from noetrium_platform.foundation.kernel.concurrency.api.ports import (
    CancellationTokenPort,
    ExecutionPermitPort,
    ExecutorProviderPort,
    SerialExecutionLaneProviderPort,
)

T = TypeVar("T")


class UnifiedExecutionAuthority:
    """Pure execution mechanism consuming a neutral permit Port.

    Provider routing, bounded queues, and serial-lane mechanics are owned here.
    Permit policy is injected at composition; this system owns only provider routing, bounded local queues, and serial-lane mechanics.
    """

    _SERIAL_RETRY_SECONDS = 0.01

    def __init__(
        self,
        *,
        blocking_io: ExecutorProviderPort,
        async_io: ExecutorProviderPort,
        cpu: ExecutorProviderPort,
        lane_resolver: Callable[[str, str, int | None], SerialExecutionLaneProviderPort],
        permits: ExecutionPermitPort | None,
    ) -> None:
        self._blocking_io = blocking_io
        self._async_io = async_io
        self._cpu = cpu
        self._lane_resolver = lane_resolver
        self._permits = permits

    def ensure_serial_lane(
        self,
        owner_group_id: str,
        lane_id: str,
        capacity: int | None,
    ) -> SerialExecutionLaneProviderPort:
        return self._lane_resolver(owner_group_id, lane_id, capacity)

    @staticmethod
    def _check_wait(*, deadline: Deadline | None, cancellation: CancellationTokenPort | None) -> None:
        if cancellation is not None and cancellation.cancelled:
            raise TaskCancelled(cancellation.reason or "execution permit wait cancelled")
        if deadline is not None and deadline.expired:
            raise TimeoutError("execution permit wait deadline expired")

    def _acquire(
        self,
        owner_group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ):
        if self._permits is None:
            return None
        return self._permits.acquire(
            owner_group_id,
            lane_kind,
            deadline=deadline,
            cancellation=cancellation,
        )

    @staticmethod
    def _release(lease) -> None:
        if lease is not None:
            lease.release()

    def _submit_serial(
        self,
        owner_group_id: str,
        spec: ExecutionSpec,
        fn: Callable[..., T],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        *,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ) -> Any:
        lane = self._lane_resolver(owner_group_id, spec.lane_id or "", spec.capacity)
        if spec.mailbox_policy is SerialMailboxPolicy.COALESCE:
            existing = lane.try_coalesce(
                spec.coalesce_key or "",
                fn,
                *args,
                cancellation=cancellation,
                **kwargs,
            )
            if existing is not None:
                return existing

        while True:
            lease = self._acquire(
                owner_group_id,
                ExecutionLaneKind.SERIAL,
                deadline=deadline,
                cancellation=cancellation,
            )
            try:
                if spec.mailbox_policy is SerialMailboxPolicy.COALESCE:
                    outcome = lane.try_submit_coalesced(
                        spec.coalesce_key or "",
                        fn,
                        *args,
                        cancellation=cancellation,
                        **kwargs,
                    )
                    if outcome is None:
                        raw = None
                        enqueued_new = False
                        work_completion = None
                    else:
                        raw, enqueued_new, work_completion = outcome
                else:
                    raw = lane.try_submit(fn, *args, cancellation=cancellation, **kwargs)
                    enqueued_new = raw is not None
                    work_completion = raw
            except BaseException:
                self._release(lease)
                raise
            if raw is not None:
                if enqueued_new:
                    assert work_completion is not None
                    work_completion.add_done_callback(lambda _handle: self._release(lease))
                else:
                    self._release(lease)
                return raw
            self._release(lease)
            if spec.mailbox_policy is SerialMailboxPolicy.REJECT:
                raise SerialMailboxRejected(
                    f"serial lane backpressure rejected task: {owner_group_id}/{spec.task_id}"
                )
            self._check_wait(deadline=deadline, cancellation=cancellation)
            wait_for = self._SERIAL_RETRY_SECONDS
            if deadline is not None:
                wait_for = min(wait_for, deadline.remaining_seconds)
            if cancellation is not None and cancellation.wait(wait_for):
                raise TaskCancelled(cancellation.reason or "serial execution permit wait cancelled")
            if cancellation is None:
                time.sleep(wait_for)

    def submit(
        self,
        owner_group_id: str,
        spec: ExecutionSpec,
        fn: Callable[..., T],
        /,
        *args: Any,
        deadline: Deadline | None = None,
        cancellation: CancellationTokenPort | None = None,
        **kwargs: Any,
    ) -> Any:
        if spec.lane_kind is ExecutionLaneKind.SERIAL:
            return self._submit_serial(
                owner_group_id,
                spec,
                fn,
                args,
                kwargs,
                deadline=deadline,
                cancellation=cancellation,
            )
        if spec.lane_kind is ExecutionLaneKind.BLOCKING_IO:
            provider = self._blocking_io
        elif spec.lane_kind is ExecutionLaneKind.ASYNC_IO:
            provider = self._async_io
        elif spec.lane_kind is ExecutionLaneKind.CPU:
            provider = self._cpu
        else:
            raise ValueError(f"unsupported execution lane: {spec.lane_kind}")

        lease = self._acquire(
            owner_group_id,
            spec.lane_kind,
            deadline=deadline,
            cancellation=cancellation,
        )
        try:
            raw = provider.submit(
                fn,
                *args,
                deadline=deadline,
                cancellation=cancellation,
                **kwargs,
            )
        except BaseException:
            self._release(lease)
            raise
        if lease is not None:
            raw.add_done_callback(lambda _handle: lease.release())
        return raw


__all__ = ["UnifiedExecutionAuthority"]
