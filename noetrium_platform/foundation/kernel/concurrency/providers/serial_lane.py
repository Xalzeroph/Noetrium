from __future__ import annotations

from collections import deque
from concurrent.futures import Future
from dataclasses import dataclass
from threading import Condition, Lock, Thread
import time
from typing import Any, Callable, Generic, TypeVar

from noetrium_platform.foundation.kernel.concurrency.api import (
    CancellationTokenPort,
    Deadline,
    SerialLaneTopologySnapshot,
    TaskCancelled,
)

T = TypeVar("T")


class _FutureHandle(Generic[T]):
    def __init__(self, future: Future[T]) -> None:
        self._future = future
        self._completed_monotonic: float | None = None
        self._completion_lock = Lock()
        future.add_done_callback(self._capture_completion)

    def _capture_completion(self, _future: Future[T]) -> None:
        completed = time.monotonic()
        with self._completion_lock:
            if self._completed_monotonic is None:
                self._completed_monotonic = completed

    def done(self) -> bool:
        return self._future.done()

    def running(self) -> bool:
        return self._future.running()

    def cancel(self) -> bool:
        return self._future.cancel()

    def result(self, timeout: float | None = None) -> T:
        return self._future.result(timeout=timeout)

    def cancelled(self) -> bool:
        return self._future.cancelled()

    @property
    def completed_monotonic(self) -> float | None:
        with self._completion_lock:
            return self._completed_monotonic

    def add_done_callback(self, callback: Callable[["_FutureHandle[T]"], None]) -> None:
        self._future.add_done_callback(lambda _future: callback(self))


@dataclass(slots=True)
class _WorkItem:
    futures: list[Future[Any]]
    completion: Future[Any]
    fn: Callable[..., Any]
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    coalesce_key: str | None = None


class SharedSerialExecutionLane:
    """One FIFO mutable-authority lane multiplexed onto shared serial workers.

    A lane owns ordering and mailbox capacity, not a dedicated thread.  At most
    one item from a lane can be executing or scheduled at a time, while distinct
    lanes may run concurrently on the factory's fixed worker set.
    """

    _ADMISSION_POLL_SECONDS = 0.05

    def __init__(
        self,
        lane_id: str,
        *,
        capacity: int,
        coordinator: "SharedSerialExecutionLaneFactory",
        worker_index: int,
        shutdown_timeout_seconds: float,
    ) -> None:
        if not lane_id.strip():
            raise ValueError("serial lane id required")
        if capacity <= 0:
            raise ValueError("serial lane capacity must be positive")
        if shutdown_timeout_seconds <= 0:
            raise ValueError("serial lane shutdown timeout must be positive")
        self._lane_id = lane_id
        self._capacity = int(capacity)
        self._coordinator = coordinator
        self._worker_index = int(worker_index)
        self._shutdown_timeout_seconds = float(shutdown_timeout_seconds)
        self._items: deque[_WorkItem] = deque()
        self._coalesced: dict[str, _WorkItem] = {}
        self._condition = Condition()
        self._closed = False
        self._scheduled = False
        self._running = False
        self._running_logical_count = 0
        self._accepted_work_items_total = 0
        self._completed_work_items_total = 0
        self._failed_work_items_total = 0
        self._coalesced_submissions_total = 0
        self._mailbox_full_events_total = 0
        self._max_queue_depth = 0

    @property
    def lane_id(self) -> str:
        return self._lane_id

    @staticmethod
    def _cancelled(cancellation: CancellationTokenPort | None) -> bool:
        return cancellation is not None and cancellation.cancelled

    def _enqueue(self, item: _WorkItem) -> bool:
        self._items.append(item)
        self._accepted_work_items_total += 1
        self._max_queue_depth = max(self._max_queue_depth, len(self._items))
        if self._scheduled:
            return False
        self._scheduled = True
        return True

    def submit(
        self,
        fn: Callable[..., T],
        /,
        *args: Any,
        deadline: Deadline | None = None,
        cancellation: CancellationTokenPort | None = None,
        **kwargs: Any,
    ) -> _FutureHandle[T]:
        future: Future[T] = Future()
        item = _WorkItem([future], Future(), fn, args, kwargs)
        schedule = False
        with self._condition:
            while len(self._items) >= self._capacity:
                self._mailbox_full_events_total += 1
                if self._closed:
                    raise RuntimeError(f"serial lane closed: {self._lane_id}")
                if self._cancelled(cancellation):
                    raise TaskCancelled(cancellation.reason or "serial lane capacity wait cancelled")
                remaining = None if deadline is None else deadline.remaining_seconds
                if remaining is not None and remaining <= 0:
                    raise TimeoutError("serial lane capacity wait deadline expired")
                wait_for = self._ADMISSION_POLL_SECONDS if remaining is None else min(
                    self._ADMISSION_POLL_SECONDS,
                    remaining,
                )
                self._condition.wait(wait_for)
            if self._closed:
                raise RuntimeError(f"serial lane closed: {self._lane_id}")
            if self._cancelled(cancellation):
                raise TaskCancelled(cancellation.reason or "serial lane capacity wait cancelled")
            if deadline is not None and deadline.expired:
                raise TimeoutError("serial lane capacity wait deadline expired")
            schedule = self._enqueue(item)
            self._condition.notify_all()
        if schedule:
            self._coordinator._schedule(self)
        return _FutureHandle(future)

    def try_submit(
        self,
        fn: Callable[..., T],
        /,
        *args: Any,
        cancellation: CancellationTokenPort | None = None,
        **kwargs: Any,
    ) -> _FutureHandle[T] | None:
        future: Future[T] = Future()
        item = _WorkItem([future], Future(), fn, args, kwargs)
        schedule = False
        with self._condition:
            if self._closed:
                raise RuntimeError(f"serial lane closed: {self._lane_id}")
            if self._cancelled(cancellation):
                raise TaskCancelled(cancellation.reason or "serial lane capacity wait cancelled")
            if len(self._items) >= self._capacity:
                self._mailbox_full_events_total += 1
                return None
            schedule = self._enqueue(item)
            self._condition.notify_all()
        if schedule:
            self._coordinator._schedule(self)
        return _FutureHandle(future)

    def try_coalesce(
        self,
        coalesce_key: str,
        fn: Callable[..., T],
        /,
        *args: Any,
        cancellation: CancellationTokenPort | None = None,
        **kwargs: Any,
    ) -> _FutureHandle[T] | None:
        key = str(coalesce_key).strip()
        if not key:
            raise ValueError("serial coalesce key required")
        future: Future[T] = Future()
        with self._condition:
            if self._closed:
                raise RuntimeError(f"serial lane closed: {self._lane_id}")
            if self._cancelled(cancellation):
                raise TaskCancelled(cancellation.reason or "serial lane capacity wait cancelled")
            item = self._coalesced.get(key)
            if item is None:
                return None
            item.fn = fn
            item.args = args
            item.kwargs = kwargs
            item.futures.append(future)
            self._coalesced_submissions_total += 1
            self._condition.notify_all()
        return _FutureHandle(future)

    def try_submit_coalesced(
        self,
        coalesce_key: str,
        fn: Callable[..., T],
        /,
        *args: Any,
        cancellation: CancellationTokenPort | None = None,
        **kwargs: Any,
    ) -> tuple[_FutureHandle[T], bool, _FutureHandle[Any] | None] | None:
        key = str(coalesce_key).strip()
        if not key:
            raise ValueError("serial coalesce key required")
        future: Future[T] = Future()
        schedule = False
        with self._condition:
            if self._closed:
                raise RuntimeError(f"serial lane closed: {self._lane_id}")
            if self._cancelled(cancellation):
                raise TaskCancelled(cancellation.reason or "serial lane capacity wait cancelled")
            existing = self._coalesced.get(key)
            if existing is not None:
                existing.fn = fn
                existing.args = args
                existing.kwargs = kwargs
                existing.futures.append(future)
                self._coalesced_submissions_total += 1
                self._condition.notify_all()
                return _FutureHandle(future), False, None
            if len(self._items) >= self._capacity:
                self._mailbox_full_events_total += 1
                return None
            completion: Future[Any] = Future()
            item = _WorkItem([future], completion, fn, args, kwargs, coalesce_key=key)
            self._coalesced[key] = item
            schedule = self._enqueue(item)
            self._condition.notify_all()
        if schedule:
            self._coordinator._schedule(self)
        return _FutureHandle(future), True, _FutureHandle(completion)

    def _take_owned_item(self) -> _WorkItem | None:
        with self._condition:
            if not self._scheduled:
                raise RuntimeError(f"serial lane scheduled-state corruption: {self._lane_id}")
            if not self._items:
                self._scheduled = False
                self._condition.notify_all()
                return None
            self._running = True
            item = self._items.popleft()
            self._running_logical_count = len(item.futures)
            if item.coalesce_key is not None:
                current = self._coalesced.get(item.coalesce_key)
                if current is item:
                    self._coalesced.pop(item.coalesce_key, None)
            self._condition.notify_all()
            return item

    def _finish_owned_item(self) -> bool:
        with self._condition:
            self._running = False
            self._running_logical_count = 0
            if self._items:
                reschedule = True
            else:
                self._scheduled = False
                reschedule = False
            self._condition.notify_all()
            return reschedule

    def topology_snapshot(self, *, owner_group_id: str, closed: bool) -> SerialLaneTopologySnapshot:
        with self._condition:
            logical_outstanding = self._running_logical_count + sum(len(item.futures) for item in self._items)
            return SerialLaneTopologySnapshot(
                lane_id=self._lane_id,
                owner_group_id=owner_group_id,
                capacity=self._capacity,
                closed=bool(closed or self._closed),
                queued_work_items=len(self._items),
                running=self._running,
                scheduled=self._scheduled,
                coalesced_keys=len(self._coalesced),
                logical_outstanding=logical_outstanding,
                accepted_work_items_total=self._accepted_work_items_total,
                completed_work_items_total=self._completed_work_items_total,
                failed_work_items_total=self._failed_work_items_total,
                coalesced_submissions_total=self._coalesced_submissions_total,
                mailbox_full_events_total=self._mailbox_full_events_total,
                max_queue_depth=self._max_queue_depth,
            )

    def close(self, *, cancel_pending: bool = False, deadline: Deadline | None = None) -> None:
        """Seal the lane and converge accepted work.

        Algorithm-Complexity: O(N)
        Algorithm-Rationale: N is the total logical watcher futures across queued work items; each queued item and each watcher is cancelled at most once, so the nested syntax partitions one aggregate population rather than multiplying independent dimensions.
        """
        effective = deadline or Deadline.after(self._shutdown_timeout_seconds)
        with self._condition:
            self._closed = True
            if cancel_pending:
                while self._items:
                    item = self._items.popleft()
                    if item.coalesce_key is not None:
                        self._coalesced.pop(item.coalesce_key, None)
                    for future in item.futures:
                        future.cancel()
                    item.completion.cancel()
                # A scheduled lane may already have a ready token published in
                # the factory queue. Keep _scheduled true until the pinned
                # worker consumes that token; clearing it here would turn the
                # token stale and could terminate the shared worker on the
                # scheduled-state invariant.
            self._condition.notify_all()
            while self._running or self._scheduled or self._items:
                remaining = effective.remaining_seconds
                if remaining <= 0:
                    raise TimeoutError(f"serial lane did not converge before deadline: {self._lane_id}")
                self._condition.wait(remaining)


class SharedSerialExecutionLaneFactory:
    """Fixed worker authority for arbitrarily many independently ordered lanes."""

    def __init__(
        self,
        *,
        max_workers: int,
        shutdown_timeout_seconds: float = 30.0,
        thread_name_prefix: str = "platform-serial",
    ) -> None:
        if max_workers <= 0:
            raise ValueError("serial worker count must be positive")
        if shutdown_timeout_seconds <= 0:
            raise ValueError("serial lane factory shutdown timeout must be positive")
        self._shutdown_timeout_seconds = float(shutdown_timeout_seconds)
        self._condition = Condition()
        self._ready = tuple(deque() for _ in range(int(max_workers)))
        self._lanes: list[SharedSerialExecutionLane] = []
        self._closed = False
        self._next_worker = 0
        self._threads = tuple(
            Thread(
                target=self._run,
                args=(index,),
                name=f"{thread_name_prefix}:{index}",
                daemon=False,
            )
            for index in range(int(max_workers))
        )
        for thread in self._threads:
            thread.start()

    def create(self, lane_id: str, *, capacity: int) -> SharedSerialExecutionLane:
        with self._condition:
            if self._closed:
                raise RuntimeError("serial lane factory is closed")
            worker_index = self._next_worker
            self._next_worker = (self._next_worker + 1) % len(self._threads)
            lane = SharedSerialExecutionLane(
                lane_id,
                capacity=capacity,
                coordinator=self,
                worker_index=worker_index,
                shutdown_timeout_seconds=self._shutdown_timeout_seconds,
            )
            self._lanes.append(lane)
            return lane

    def _schedule(self, lane: SharedSerialExecutionLane) -> None:
        with self._condition:
            if self._closed:
                raise RuntimeError("serial lane factory is closed")
            self._ready[lane._worker_index].append(lane)
            self._condition.notify_all()

    def _run(self, worker_index: int) -> None:
        """Run one pinned serial worker until the factory closes.

        Concurrency-Policy: OWNED_CONDITION_WAIT
        Concurrency-Rationale: The factory owns this non-daemon worker and close() broadcasts then joins every worker before returning.
        """
        ready = self._ready[worker_index]
        while True:
            with self._condition:
                while not ready and not self._closed:
                    self._condition.wait()
                if not ready and self._closed:
                    return
                lane = ready.popleft()
            item = lane._take_owned_item()
            if item is None:
                continue
            completion_active = item.completion.set_running_or_notify_cancel()
            active = [future for future in item.futures if future.set_running_or_notify_cancel()]
            if completion_active:
                if active:
                    try:
                        result = item.fn(*item.args, **item.kwargs)
                    except BaseException as exc:
                        for future in active:
                            future.set_exception(exc)
                        item.completion.set_exception(exc)
                        with lane._condition:
                            lane._failed_work_items_total += 1
                    else:
                        for future in active:
                            future.set_result(result)
                        item.completion.set_result(result)
                        with lane._condition:
                            lane._completed_work_items_total += 1
                else:
                    item.completion.set_result(None)
                    with lane._condition:
                        lane._completed_work_items_total += 1
            if lane._finish_owned_item():
                self._schedule(lane)

    def close(
        self,
        *,
        cancel_pending: bool = False,
        deadline: Deadline | None = None,
    ) -> None:
        effective = deadline or Deadline.after(self._shutdown_timeout_seconds)
        with self._condition:
            lanes = tuple(self._lanes)
        errors: list[BaseException] = []
        for lane in lanes:
            try:
                lane.close(cancel_pending=cancel_pending, deadline=effective)
            except BaseException as exc:
                errors.append(exc)
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        for thread in self._threads:
            thread.join(timeout=effective.remaining_seconds)
            if thread.is_alive():
                errors.append(TimeoutError(f"serial worker did not terminate before deadline: {thread.name}"))
        if errors:
            raise ExceptionGroup("serial lane factory shutdown failed", errors)


__all__ = ["SharedSerialExecutionLane", "SharedSerialExecutionLaneFactory"]
