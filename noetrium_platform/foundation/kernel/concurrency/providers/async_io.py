from __future__ import annotations

import asyncio
from concurrent.futures import Future
import inspect
from threading import Condition, Event, Lock, Thread
import time
from typing import Any, Awaitable, Callable, Generic, TypeVar

from noetrium_platform.foundation.kernel.concurrency.api import CancellationTokenPort, Deadline, TaskCancelled

T = TypeVar("T")


class _AsyncFutureHandle(Generic[T]):
    """Bridge one logical provider handle to one physically-owned asyncio Task.

    Cancelling the public handle requests source-task cancellation but deliberately
    does not complete the proxy Future.  Physical completion owns both capacity
    release and source-task exception retrieval.
    """

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        on_physical_done: Callable[["_AsyncFutureHandle[T]"], None],
    ) -> None:
        self._future: Future[T] = Future()
        self._loop = loop
        self._on_physical_done = on_physical_done
        self._state_lock = Lock()
        self._completion_lock = Lock()
        self._source_task: asyncio.Task[T] | None = None
        self._cancel_requested = False
        self._completed_monotonic: float | None = None

    def start(self, invoke: Callable[[], Awaitable[T]]) -> None:
        """Create the source Task on the provider-owned loop thread."""
        try:
            task = self._loop.create_task(invoke())
        except BaseException as exc:
            self.fail_submission(exc)
            return
        with self._state_lock:
            self._source_task = task
            cancel_requested = self._cancel_requested
        task.add_done_callback(self._source_done)
        if cancel_requested:
            task.cancel()

    def fail_submission(self, exc: BaseException) -> None:
        self._mark_physically_done()
        self._on_physical_done(self)
        if not self._future.done():
            self._future.set_exception(exc)

    def _mark_physically_done(self) -> None:
        with self._completion_lock:
            if self._completed_monotonic is None:
                self._completed_monotonic = time.monotonic()

    def _source_done(self, task: asyncio.Task[T]) -> None:
        # Retrieving the source result here is provider ownership of every terminal
        # exception, even when the logical caller already observed a deadline and
        # no longer needs the proxy result.
        cancelled = False
        value: T | None = None
        failure: BaseException | None = None
        try:
            value = task.result()
        except asyncio.CancelledError:
            cancelled = True
        except BaseException as exc:
            failure = exc
        self._mark_physically_done()
        self._on_physical_done(self)
        if self._future.done():
            return
        if cancelled:
            self._future.cancel()
        elif failure is not None:
            self._future.set_exception(failure)
        else:
            self._future.set_result(value)  # type: ignore[arg-type]

    def done(self) -> bool:
        return self._future.done()

    def running(self) -> bool:
        with self._state_lock:
            task = self._source_task
        return task is not None and not task.done()

    def cancel(self) -> bool:
        with self._state_lock:
            if self._future.done() or self._cancel_requested:
                return False
            self._cancel_requested = True
            task = self._source_task
        if task is not None:
            self._loop.call_soon_threadsafe(task.cancel)
        return True

    def cancelled(self) -> bool:
        return self._future.cancelled()

    def result(self, timeout: float | None = None) -> T:
        return self._future.result(timeout=timeout)

    def add_done_callback(self, callback: Callable[["_AsyncFutureHandle[T]"], None]) -> None:
        self._future.add_done_callback(lambda _future: callback(self))

    @property
    def completed_monotonic(self) -> float | None:
        with self._completion_lock:
            return self._completed_monotonic


class AsyncIoExecutor:
    """One event-loop thread with bounded coroutine submission capacity.

    The loop is provider-owned and business systems cannot create tasks directly.
    Every coroutine enters through TaskGroup ownership, so cancellation/deadline
    state remains visible in the same topology as thread/process/serial work.
    """

    _ADMISSION_POLL_SECONDS = 0.05

    def __init__(self, *, max_in_flight: int, thread_name: str = "platform-async-io", shutdown_timeout_seconds: float = 30.0) -> None:
        if max_in_flight <= 0:
            raise ValueError("async I/O max_in_flight must be positive")
        if shutdown_timeout_seconds <= 0:
            raise ValueError("async I/O shutdown timeout must be positive")
        self._max_in_flight = int(max_in_flight)
        self._available = int(max_in_flight)
        self._shutdown_timeout_seconds = float(shutdown_timeout_seconds)
        self._condition = Condition()
        self._closed = False
        self._loop = asyncio.new_event_loop()
        self._ready = Event()
        self._thread = Thread(target=self._run, name=thread_name, daemon=False)
        self._futures: set[_AsyncFutureHandle[Any]] = set()
        self._thread.start()
        if not self._ready.wait(self._shutdown_timeout_seconds):
            raise RuntimeError("async I/O event loop failed to start")

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    @staticmethod
    def _cancelled(cancellation: CancellationTokenPort | None) -> bool:
        return cancellation is not None and cancellation.cancelled

    def _acquire(self, *, deadline: Deadline | None, cancellation: CancellationTokenPort | None) -> None:
        with self._condition:
            while self._available <= 0:
                if self._closed:
                    raise RuntimeError("async I/O executor is closed")
                if self._cancelled(cancellation):
                    raise TaskCancelled(cancellation.reason or "async I/O capacity wait cancelled")
                remaining = None if deadline is None else deadline.remaining_seconds
                if remaining is not None and remaining <= 0:
                    raise TimeoutError("async I/O capacity wait deadline expired")
                wait_for = self._ADMISSION_POLL_SECONDS if remaining is None else min(self._ADMISSION_POLL_SECONDS, remaining)
                self._condition.wait(wait_for)
            if self._closed:
                raise RuntimeError("async I/O executor is closed")
            if self._cancelled(cancellation):
                raise TaskCancelled(cancellation.reason or "async I/O capacity wait cancelled")
            if deadline is not None and deadline.expired:
                raise TimeoutError("async I/O capacity wait deadline expired")
            self._available -= 1

    def _release(self, future: _AsyncFutureHandle[Any]) -> None:
        with self._condition:
            self._futures.discard(future)
            self._available += 1
            if self._available > self._max_in_flight:
                raise RuntimeError("async I/O capacity accounting overflow")
            self._condition.notify_all()

    def submit(
        self,
        fn: Callable[..., T],
        /,
        *args: Any,
        deadline: Deadline | None = None,
        cancellation: CancellationTokenPort | None = None,
        **kwargs: Any,
    ) -> _AsyncFutureHandle[T]:
        self._acquire(deadline=deadline, cancellation=cancellation)

        async def invoke() -> T:
            value = fn(*args, **kwargs)
            if not inspect.isawaitable(value):
                raise TypeError("ASYNC_IO execution callable must return an awaitable")
            return await value

        future = _AsyncFutureHandle[T](loop=self._loop, on_physical_done=self._release)
        # Provider ownership starts before the loop callback is scheduled so close()
        # and admission accounting can observe every acquired capacity slot.
        with self._condition:
            self._futures.add(future)
            closed = self._closed
        if closed:
            future.cancel()
        try:
            self._loop.call_soon_threadsafe(future.start, invoke)
        except BaseException as exc:
            future.fail_submission(exc)
            raise
        return future

    async def _cancel_all_tasks(self) -> None:
        current = asyncio.current_task()
        tasks = [task for task in asyncio.all_tasks() if task is not current and not task.done()]
        for task in tasks:
            if task.cancelling() == 0:
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def close(self, *, wait: bool = True, cancel_pending: bool = False) -> None:
        with self._condition:
            already_closed = self._closed
            self._closed = True
            futures = tuple(self._futures)
            self._condition.notify_all()
        if cancel_pending:
            for future in futures:
                future.cancel()
        if self._thread.is_alive() and not already_closed:
            shutdown = asyncio.run_coroutine_threadsafe(self._cancel_all_tasks(), self._loop)
            if wait:
                try:
                    shutdown.result(timeout=self._shutdown_timeout_seconds)
                finally:
                    self._loop.call_soon_threadsafe(self._loop.stop)
            else:
                shutdown.add_done_callback(lambda _future: self._loop.call_soon_threadsafe(self._loop.stop))
        elif self._thread.is_alive() and wait:
            # A prior non-blocking close already owns shutdown and schedules loop
            # stop only after source Tasks physically finish.  A later waiting
            # close must join that shutdown, never stop the loop out from under it.
            pass
        if wait:
            self._thread.join(timeout=self._shutdown_timeout_seconds)
            if self._thread.is_alive():
                raise TimeoutError("async I/O executor did not terminate")


__all__ = ["AsyncIoExecutor"]
