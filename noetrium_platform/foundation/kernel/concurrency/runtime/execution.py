from __future__ import annotations

from threading import Event, Lock
import time
from typing import Any, Callable, Generic, TypeVar

from noetrium_platform.foundation.kernel.concurrency.api import (
    SerialMailboxPolicy,
    SerialMailboxRejected,
    Deadline,
    ExecutionLaneKind,
    ExecutionSpec,
    PhysicalJoinTimeout,
    TaskCancelled,
)
from noetrium_platform.foundation.kernel.concurrency.api.ports import (
    AtomicBatchExecutorProviderPort,
    CancellationTokenPort,
    ExecutionPermitPort,
    ExecutorProviderPort,
    ExecutionRetirementProviderPort,
    SerialExecutionLaneProviderPort,
)

T = TypeVar("T")


class _CompletionFencedHandle(Generic[T]):
    """Expose provider completion only after owned execution capacity is released.

    Provider Futures become terminal before their callbacks necessarily finish.
    Without this fence, a caller can observe result() and immediately refill
    work while the physical provider slot or resource permit is still owned.
    The fence makes capacity release part of the execution completion contract.
    """

    def __init__(
        self,
        raw,
        release: Callable[[], None],
        *,
        blocking_release_provider: ExecutionRetirementProviderPort | None = None,
    ) -> None:
        self._raw = raw
        self._release = release
        self._blocking_release_provider = blocking_release_provider
        self._release_visible = Event()
        self._release_lock = Lock()
        self._release_started = False
        self._release_failure: BaseException | None = None
        self._completion_callbacks: list[
            Callable[["_CompletionFencedHandle[T]"], None]
        ] = []
        # Diagnostic callback failures are auxiliary: they never rewrite the
        # accepted physical task outcome. Preserve exact exceptions locally
        # for the composing Observability/Failure Authority instead of using
        # an out-of-layer stdlib logger in the Kernel callback thread.
        self._completion_observer_failures: list[Exception] = []
        raw.add_done_callback(self._on_raw_done)

    def completion_observer_failures(self) -> tuple[Exception, ...]:
        with self._release_lock:
            return tuple(self._completion_observer_failures)

    def _notify_observer(self, callback: Callable[["_CompletionFencedHandle[T]"], None]) -> None:
        try:
            callback(self)
        except Exception as exc:
            with self._release_lock:
                self._completion_observer_failures.append(exc)

    def _retire_permit_once(self) -> None:
        # The fallback callback can race with an ordinary worker completion.
        # The permit is affine and must be released exactly once in all cases.
        with self._release_lock:
            if self._release_started:
                return
            self._release_started = True
        failure: BaseException | None = None
        try:
            self._release()
        except BaseException as exc:
            failure = exc
        finally:
            with self._release_lock:
                self._release_failure = failure
                self._release_visible.set()
                callbacks = tuple(self._completion_callbacks)
                self._completion_callbacks.clear()
            # Completion subscriptions must not wait on an Event in the raw
            # provider's callback thread: for ASYNC_IO that is the HTTP loop.
            # The release worker publishes exactly one completion after the
            # permit is fully retired, with no polling and no blocked loop.
            for callback in callbacks:
                self._notify_observer(callback)

    def _on_raw_done(self, _handle) -> None:
        provider = self._blocking_release_provider
        if provider is not None:
            try:
                # An accepted ASYNC_IO task already owns its execution permit.
                # Terminal cleanup inherits that authorization and can be
                # enqueued onto the owned retirement provider even when the
                # ordinary workload workers are saturated, without blocking
                # the raw HTTP event-loop completion callback.
                handle = provider.submit_inherited_retirement(
                    self._retire_permit_once
                )
                # Cancel-before-start still must retire the affine permit.
                handle.add_done_callback(
                    lambda _child: self._retire_permit_once()
                )
                return
            except BaseException:
                # Provider unexpectedly unavailable: never leak a permit.
                pass
        self._retire_permit_once()

    def _release_error(self) -> BaseException | None:
        with self._release_lock:
            return self._release_failure

    def done(self) -> bool:
        return bool(self._raw.done()) and self._release_visible.is_set()

    def running(self) -> bool:
        return bool(self._raw.running())

    def cancel(self) -> bool:
        return bool(self._raw.cancel())

    def cancelled(self) -> bool:
        return bool(self._raw.cancelled())

    @property
    def completed_monotonic(self):
        return getattr(self._raw, "completed_monotonic", None)

    def add_done_callback(
        self,
        callback: Callable[["_CompletionFencedHandle[T]"], None],
    ) -> None:
        if not callable(callback):
            raise TypeError("physical completion callback must be callable")
        with self._release_lock:
            already_released = self._release_visible.is_set()
            if not already_released:
                self._completion_callbacks.append(callback)
        if already_released:
            self._notify_observer(callback)

    def result(self, timeout: float | None = None) -> T:
        started = time.monotonic()
        value: T | None = None
        raw_failure: BaseException | None = None
        try:
            value = self._raw.result(timeout=timeout)
        except PhysicalJoinTimeout:
            # A physical wait timeout remains such even if the child becomes
            # terminal before this exception is handled.
            raise
        except BaseException as exc:
            # A caller wait timeout is not a terminal task result and therefore
            # has no completion fence to await yet.
            if isinstance(exc, TimeoutError) and not self._raw.done():
                raise
            raw_failure = exc

        remaining = None
        if timeout is not None:
            remaining = max(0.0, float(timeout) - (time.monotonic() - started))
        if not self._release_visible.wait(remaining):
            raise PhysicalJoinTimeout(
                "execution completion capacity-release fence wait expired"
            )

        release_failure = self._release_error()
        if raw_failure is not None and release_failure is not None:
            raise BaseExceptionGroup(
                "execution and capacity release both failed",
                [raw_failure, release_failure],
            )
        if raw_failure is not None:
            raise raw_failure
        if release_failure is not None:
            raise release_failure
        return value  # type: ignore[return-value]


class UnifiedExecutionAuthority:
    """Pure execution mechanism consuming a neutral permit Port.

    Provider routing, bounded queues, and serial-lane mechanics are owned here.
    Permit policy is injected at composition; this system owns only provider routing, bounded local queues, and serial-lane mechanics.
    """

    def __init__(
        self,
        *,
        blocking_io: AtomicBatchExecutorProviderPort,
        async_io: ExecutorProviderPort,
        retirement_io: ExecutionRetirementProviderPort,
        cpu: ExecutorProviderPort,
        lane_resolver: Callable[[str, str, int | None], SerialExecutionLaneProviderPort],
        permits: ExecutionPermitPort | None,
    ) -> None:
        self._blocking_io = blocking_io
        self._async_io = async_io
        self._retirement_io = retirement_io
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

    def _try_acquire(
        self,
        owner_group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ):
        if self._permits is None:
            return None
        return self._permits.try_acquire(
            owner_group_id,
            lane_kind,
            deadline=deadline,
            cancellation=cancellation,
        )

    def _acquire_many(
        self,
        owner_group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        permit_count: int,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ) -> tuple[object | None, ...]:
        if type(permit_count) is not int or permit_count <= 0:
            raise ValueError("execution permit_count must be a positive integer")
        if self._permits is None:
            return tuple(None for _ in range(permit_count))
        leases = self._permits.acquire_many(
            owner_group_id,
            lane_kind,
            permit_count=permit_count,
            deadline=deadline,
            cancellation=cancellation,
        )
        if len(leases) != permit_count:
            for lease in leases:
                lease.release()
            raise RuntimeError(
                "execution permit authority returned invalid batch cardinality"
            )
        return tuple(leases)

    def _try_acquire_many(
        self,
        owner_group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        permit_count: int,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ) -> tuple[object | None, ...] | None:
        if type(permit_count) is not int or permit_count <= 0:
            raise ValueError("execution permit_count must be a positive integer")
        if self._permits is None:
            return None
        leases = self._permits.try_acquire_many(
            owner_group_id,
            lane_kind,
            permit_count=permit_count,
            deadline=deadline,
            cancellation=cancellation,
        )
        if leases is None:
            return None
        if len(leases) != permit_count:
            for lease in leases:
                lease.release()
            raise RuntimeError(
                "execution permit authority returned invalid "
                "nonblocking batch cardinality"
            )
        return tuple(leases)

    def _try_acquire_up_to(
        self,
        owner_group_id: str,
        lane_kind: ExecutionLaneKind,
        *,
        max_permit_count: int,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ) -> tuple[object | None, ...]:
        if type(max_permit_count) is not int or max_permit_count <= 0:
            raise ValueError(
                "execution max_permit_count must be a positive integer"
            )
        if self._permits is None:
            return tuple(None for _ in range(max_permit_count))
        leases = self._permits.try_acquire_up_to(
            owner_group_id,
            lane_kind,
            max_permit_count=max_permit_count,
            deadline=deadline,
            cancellation=cancellation,
        )
        if len(leases) > max_permit_count:
            for lease in leases:
                lease.rollback()
            raise RuntimeError(
                "execution permit authority exceeded maximal batch upper bound"
            )
        return tuple(leases)

    @staticmethod
    def _rollback(lease) -> None:
        if lease is not None:
            lease.rollback()

    @staticmethod
    def _release(lease) -> None:
        if lease is not None:
            lease.release()

    def _completion_fence(
        self,
        raw,
        lease,
        *,
        asynchronous_release: bool = False,
    ):
        return _CompletionFencedHandle(
            raw,
            ((lambda: None) if lease is None else lease.release),
            blocking_release_provider=(
                self._retirement_io
                if asynchronous_release and lease is not None
                else None
            ),
        )

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
            # The mailbox, not the execution coordinator, owns its capacity
            # predicate and its wakeup source. Never impose a polling clock.
            lane.wait_for_capacity(deadline=deadline, cancellation=cancellation)

    def submit_atomic_batch(
        self,
        owner_group_id: str,
        lane_kind: ExecutionLaneKind,
        fns: tuple[Callable[[], T], ...],
        *,
        deadline: Deadline | None = None,
        cancellation: CancellationTokenPort | None = None,
    ) -> tuple[Any, ...]:
        if lane_kind not in {
            ExecutionLaneKind.BLOCKING_IO,
            ExecutionLaneKind.ASYNC_IO,
        }:
            raise ValueError(
                "atomic execution batch requires BLOCKING_IO or ASYNC_IO"
            )
        if not isinstance(fns, tuple) or not fns:
            raise ValueError("atomic execution batch requires a non-empty tuple")
        if any(not callable(fn) for fn in fns):
            raise TypeError("atomic execution batch entries must be callable")

        leases = self._acquire_many(
            owner_group_id,
            lane_kind,
            permit_count=len(fns),
            deadline=deadline,
            cancellation=cancellation,
        )
        provider = (
            self._blocking_io
            if lane_kind is ExecutionLaneKind.BLOCKING_IO
            else self._async_io
        )
        try:
            raw_handles = provider.submit_atomic_batch(
                fns,
                deadline=deadline,
                cancellation=cancellation,
            )
        except BaseException:
            for lease in leases:
                self._release(lease)
            raise

        if len(raw_handles) != len(leases):
            for raw in raw_handles:
                try:
                    raw.cancel()
                except BaseException:
                    pass
            for lease in leases:
                self._release(lease)
            raise RuntimeError(
                "atomic provider returned invalid batch cardinality"
            )
        return tuple(
            self._completion_fence(
                raw, lease,
                asynchronous_release=lane_kind is ExecutionLaneKind.ASYNC_IO,
            )
            for raw, lease in zip(raw_handles, leases, strict=True)
        )

    def try_submit_atomic_batch(
        self,
        owner_group_id: str,
        lane_kind: ExecutionLaneKind,
        fns: tuple[Callable[[], T], ...],
        *,
        deadline: Deadline | None = None,
        cancellation: CancellationTokenPort | None = None,
    ) -> tuple[Any, ...] | None:
        """Submit one all-or-none batch immediately or return None."""

        if lane_kind not in {
            ExecutionLaneKind.BLOCKING_IO,
            ExecutionLaneKind.ASYNC_IO,
        }:
            raise ValueError(
                "atomic execution batch requires BLOCKING_IO or ASYNC_IO"
            )
        if not isinstance(fns, tuple) or not fns:
            raise ValueError(
                "atomic execution batch requires a non-empty tuple"
            )
        if any(not callable(fn) for fn in fns):
            raise TypeError("atomic execution batch entries must be callable")

        leases = self._try_acquire_many(
            owner_group_id,
            lane_kind,
            permit_count=len(fns),
            deadline=deadline,
            cancellation=cancellation,
        )
        if leases is None:
            return None
        provider = (
            self._blocking_io
            if lane_kind is ExecutionLaneKind.BLOCKING_IO
            else self._async_io
        )
        try:
            raw_handles = provider.try_submit_atomic_batch(
                fns,
                deadline=deadline,
                cancellation=cancellation,
            )
        except BaseException:
            for lease in leases:
                self._release(lease)
            raise
        if raw_handles is None:
            for lease in leases:
                self._release(lease)
            return None

        if len(raw_handles) != len(leases):
            for raw in raw_handles:
                try:
                    raw.cancel()
                except BaseException:
                    pass
            for lease in leases:
                self._release(lease)
            raise RuntimeError(
                "atomic provider returned invalid nonblocking batch cardinality"
            )
        return tuple(
            self._completion_fence(
                raw, lease,
                asynchronous_release=lane_kind is ExecutionLaneKind.ASYNC_IO,
            )
            for raw, lease in zip(raw_handles, leases, strict=True)
        )

    def try_submit_maximal_batch(
        self,
        owner_group_id: str,
        lane_kind: ExecutionLaneKind,
        fns: tuple[Callable[[], T], ...],
        *,
        deadline: Deadline | None = None,
        cancellation: CancellationTokenPort | None = None,
    ) -> tuple[Any, ...]:
        """Submit the maximal immediately executable prefix of one ready set.

        Admission owns policy cardinality; the provider owns physical slot
        availability. This method computes their atomic intersection and
        rolls back every provisional permit that does not reach execution.
        """

        if lane_kind not in {
            ExecutionLaneKind.BLOCKING_IO,
            ExecutionLaneKind.ASYNC_IO,
        }:
            raise ValueError(
                "maximal execution batch requires BLOCKING_IO or ASYNC_IO"
            )
        if not isinstance(fns, tuple) or not fns:
            raise ValueError(
                "maximal execution batch requires a non-empty tuple"
            )
        if any(not callable(fn) for fn in fns):
            raise TypeError("maximal execution batch entries must be callable")

        leases = self._try_acquire_up_to(
            owner_group_id,
            lane_kind,
            max_permit_count=len(fns),
            deadline=deadline,
            cancellation=cancellation,
        )
        if not leases:
            return ()

        provider = (
            self._blocking_io
            if lane_kind is ExecutionLaneKind.BLOCKING_IO
            else self._async_io
        )
        try:
            raw_handles = provider.try_submit_maximal_batch(
                fns[:len(leases)],
                deadline=deadline,
                cancellation=cancellation,
            )
        except BaseException:
            for lease in leases:
                self._rollback(lease)
            raise

        if len(raw_handles) > len(leases):
            for raw in raw_handles:
                try:
                    raw.cancel()
                except BaseException:
                    pass
            for lease in leases:
                self._rollback(lease)
            raise RuntimeError(
                "physical provider exceeded authorized maximal batch"
            )

        admitted = len(raw_handles)
        for lease in leases[admitted:]:
            self._rollback(lease)
        if admitted == 0:
            return ()

        return tuple(
            self._completion_fence(
                raw, lease,
                asynchronous_release=lane_kind is ExecutionLaneKind.ASYNC_IO,
            )
            for raw, lease in zip(
                raw_handles,
                leases[:admitted],
                strict=True,
            )
        )

    def try_submit(
        self,
        owner_group_id: str,
        spec: ExecutionSpec,
        fn: Callable[..., T],
        /,
        *args: Any,
        deadline: Deadline | None = None,
        cancellation: CancellationTokenPort | None = None,
        **kwargs: Any,
    ) -> Any | None:
        """Submit immediately or return None without joining an admission queue."""

        has_permit_authority = self._permits is not None

        if spec.lane_kind is ExecutionLaneKind.SERIAL:
            lane = self._lane_resolver(
                owner_group_id,
                spec.lane_id or "",
                spec.capacity,
            )
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
            lease = (
                self._try_acquire(
                    owner_group_id,
                    ExecutionLaneKind.SERIAL,
                    deadline=deadline,
                    cancellation=cancellation,
                )
                if has_permit_authority
                else None
            )
            if has_permit_authority and lease is None:
                return None
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
                    raw = lane.try_submit(
                        fn,
                        *args,
                        cancellation=cancellation,
                        **kwargs,
                    )
                    enqueued_new = raw is not None
                    work_completion = raw
            except BaseException:
                self._release(lease)
                raise
            if raw is None:
                self._release(lease)
                return None
            if enqueued_new:
                assert work_completion is not None
                work_completion.add_done_callback(
                    lambda _handle: self._release(lease)
                )
            else:
                self._release(lease)
            return raw

        if spec.lane_kind is ExecutionLaneKind.BLOCKING_IO:
            provider = self._blocking_io
        elif spec.lane_kind is ExecutionLaneKind.ASYNC_IO:
            provider = self._async_io
        elif spec.lane_kind is ExecutionLaneKind.CPU:
            provider = self._cpu
        else:
            raise ValueError(f"unsupported execution lane: {spec.lane_kind}")

        lease = (
            self._try_acquire(
                owner_group_id,
                spec.lane_kind,
                deadline=deadline,
                cancellation=cancellation,
            )
            if has_permit_authority
            else None
        )
        if has_permit_authority and lease is None:
            return None
        try:
            raw = provider.try_submit(
                fn,
                *args,
                deadline=deadline,
                cancellation=cancellation,
                **kwargs,
            )
        except BaseException:
            self._release(lease)
            raise
        if raw is None:
            self._release(lease)
            return None
        return self._completion_fence(
            raw, lease,
            asynchronous_release=spec.lane_kind is ExecutionLaneKind.ASYNC_IO,
        )

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
        return self._completion_fence(
            raw, lease,
            asynchronous_release=spec.lane_kind is ExecutionLaneKind.ASYNC_IO,
        )


__all__ = ["UnifiedExecutionAuthority"]
