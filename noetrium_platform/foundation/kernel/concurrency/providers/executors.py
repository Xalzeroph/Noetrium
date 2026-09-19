from __future__ import annotations

from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
import multiprocessing as mp
from threading import Condition, Lock
import time
from typing import Any, Callable, Generic, TypeVar

from noetrium_platform.foundation.kernel.concurrency.api import CancellationTokenPort, Deadline, TaskCancelled

T = TypeVar("T")


class _FutureHandle(Generic[T]):
    """Provider future plus a monotonic completion timestamp for deadline arbitration."""

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


class _BoundedExecutor:
    """Executor adapter with cancellation-aware bounded submission capacity.

    The executor's private work queue is never used as the platform backpressure
    authority.  A condition-owned in-flight budget gates every submission and can
    be interrupted by runtime shutdown, task-group cancellation, or a deadline.
    """

    _ADMISSION_POLL_SECONDS = 0.05

    def __init__(self, executor: ThreadPoolExecutor | ProcessPoolExecutor, *, max_in_flight: int) -> None:
        if max_in_flight <= 0:
            raise ValueError("max_in_flight must be positive")
        self._executor = executor
        self._max_in_flight = int(max_in_flight)
        self._available = int(max_in_flight)
        self._condition = Condition()
        self._closed = False

    @staticmethod
    def _cancelled(cancellation: CancellationTokenPort | None) -> bool:
        return cancellation is not None and cancellation.cancelled

    @staticmethod
    def _cancel_reason(cancellation: CancellationTokenPort | None) -> str:
        if cancellation is None:
            return "executor capacity wait cancelled"
        return cancellation.reason or "executor capacity wait cancelled"

    def _acquire_slot(
        self,
        *,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ) -> None:
        with self._condition:
            while self._available <= 0:
                if self._closed:
                    raise RuntimeError("executor is closed")
                if self._cancelled(cancellation):
                    raise TaskCancelled(self._cancel_reason(cancellation))
                remaining = None if deadline is None else deadline.remaining_seconds
                if remaining is not None and remaining <= 0:
                    raise TimeoutError("executor capacity wait deadline expired")
                wait_for = self._ADMISSION_POLL_SECONDS if remaining is None else min(
                    self._ADMISSION_POLL_SECONDS,
                    remaining,
                )
                self._condition.wait(wait_for)
            if self._closed:
                raise RuntimeError("executor is closed")
            if self._cancelled(cancellation):
                raise TaskCancelled(self._cancel_reason(cancellation))
            if deadline is not None and deadline.expired:
                raise TimeoutError("executor capacity wait deadline expired")
            self._available -= 1

    def _release_slot(self) -> None:
        with self._condition:
            self._available += 1
            if self._available > self._max_in_flight:
                raise RuntimeError("executor capacity slot accounting overflow")
            self._condition.notify_all()

    def submit(
        self,
        fn: Callable[..., T],
        /,
        *args: Any,
        deadline: Deadline | None = None,
        cancellation: CancellationTokenPort | None = None,
        **kwargs: Any,
    ) -> _FutureHandle[T]:
        self._acquire_slot(deadline=deadline, cancellation=cancellation)
        with self._condition:
            if self._closed:
                self._available += 1
                self._condition.notify_all()
                raise RuntimeError("executor is closed")
            if self._cancelled(cancellation):
                self._available += 1
                self._condition.notify_all()
                raise TaskCancelled(self._cancel_reason(cancellation))
            try:
                future = self._executor.submit(fn, *args, **kwargs)
            except BaseException:
                self._available += 1
                self._condition.notify_all()
                raise
        future.add_done_callback(lambda _future: self._release_slot())
        return _FutureHandle(future)

    def close(self, *, wait: bool = True, cancel_pending: bool = False) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        # Executor.shutdown() is intentionally invoked on every close call.  A
        # previous bounded shutdown may have used wait=False after a structured
        # convergence deadline was breached; a later close must still be able to
        # join the provider workers after the owned tasks have physically ended.
        self._executor.shutdown(wait=wait, cancel_futures=cancel_pending)


class BoundedThreadExecutor(_BoundedExecutor):
    def __init__(self, *, max_workers: int, max_in_flight: int, thread_name_prefix: str = "platform-io") -> None:
        super().__init__(
            ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=thread_name_prefix),
            max_in_flight=max_in_flight,
        )


class BoundedProcessExecutor(_BoundedExecutor):
    def __init__(self, *, max_workers: int, max_in_flight: int) -> None:
        # The concurrency runtime owns live threads (timer + serial lanes). Forking
        # a multithreaded process can inherit locked runtime state and deadlock.
        # Spawn gives every CPU worker a clean interpreter and is portable across
        # supported platforms; startup cost is amortized by the process pool.
        context = mp.get_context("spawn")
        super().__init__(
            ProcessPoolExecutor(max_workers=max_workers, mp_context=context),
            max_in_flight=max_in_flight,
        )

    def map(self, fn, values, *, chunksize: int = 1):
        if chunksize <= 0:
            raise ValueError("chunksize must be positive")
        with self._condition:
            if self._closed:
                raise RuntimeError("executor is closed")
        # This provider method is retained only for internal batch CPU governance;
        # business systems cannot import the provider port.  TaskGroup submissions
        # remain the owner-aware path for ordinary work.
        return tuple(self._executor.map(fn, values, chunksize=chunksize))
