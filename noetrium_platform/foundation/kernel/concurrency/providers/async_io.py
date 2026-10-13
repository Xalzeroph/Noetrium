from __future__ import annotations

import asyncio
from concurrent.futures import Future
import inspect
from threading import Condition, Event, Lock, Thread
import time
from typing import Any, Awaitable, Callable, Generic, TypeVar

from noetrium_platform.foundation.kernel.concurrency.api import CancellationTokenPort, Deadline, TaskCancelled, wake_on_cancellation, physical_future_result

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
        release_failure = self._finish_physical_release()
        if release_failure is not None:
            exc = BaseExceptionGroup(
                "ASYNC_IO submission and physical release both failed",
                [exc, release_failure],
            )
        if not self._future.done():
            self._future.set_exception(exc)

    def _finish_physical_release(self) -> BaseException | None:
        try:
            self._on_physical_done(self)
        except BaseException as exc:
            # Do not lose this failure in an asyncio done callback: the public
            # Future must always terminate, including when capacity release fails.
            return exc
        return None

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
        release_failure = self._finish_physical_release()
        if self._future.done():
            return
        if release_failure is not None:
            if failure is not None:
                release_failure = BaseExceptionGroup(
                    "ASYNC_IO source and physical capacity release both failed",
                    [failure, release_failure],
                )
            elif cancelled:
                release_failure.add_note(
                    "ASYNC_IO source task was cancelled before physical release failed"
                )
            self._future.set_exception(release_failure)
        elif cancelled:
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
        return physical_future_result(self._future, timeout)

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
        self._thread_name = str(thread_name)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = Event()
        self._thread: Thread | None = None
        self._start_lock = Lock()
        self._futures: set[_AsyncFutureHandle[Any]] = set()

    def _ensure_started(self) -> asyncio.AbstractEventLoop:
        with self._start_lock:
            with self._condition:
                if self._closed:
                    raise RuntimeError("async I/O executor is closed")
                loop = self._loop
                thread = self._thread
                if loop is not None and thread is not None:
                    return loop
            loop = asyncio.new_event_loop()
            thread = Thread(
                target=self._run,
                args=(loop,),
                name=self._thread_name,
                daemon=False,
            )
            self._ready.clear()
            with self._condition:
                if self._closed:
                    loop.close()
                    raise RuntimeError("async I/O executor is closed")
                self._loop = loop
                self._thread = thread
            try:
                thread.start()
            except BaseException:
                with self._condition:
                    self._loop = None
                    self._thread = None
                loop.close()
                raise
            if not self._ready.wait(self._shutdown_timeout_seconds):
                with self._condition:
                    self._closed = True
                loop.call_soon_threadsafe(loop.stop)
                thread.join(timeout=self._shutdown_timeout_seconds)
                raise RuntimeError("async I/O event loop failed to start")
            return loop

    def _run(self, loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            loop.close()

    @staticmethod
    def _cancelled(cancellation: CancellationTokenPort | None) -> bool:
        return cancellation is not None and cancellation.cancelled

    def _acquire(self, *, deadline: Deadline | None, cancellation: CancellationTokenPort | None) -> None:
        self._acquire_many(1, deadline=deadline, cancellation=cancellation)

    def _try_acquire(
        self,
        *,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ) -> bool:
        return self._try_acquire_many(
            1, deadline=deadline, cancellation=cancellation
        )

    def _release(self, future: _AsyncFutureHandle[Any]) -> None:
        with self._condition:
            self._futures.discard(future)
            self._available += 1
            if self._available > self._max_in_flight:
                raise RuntimeError("async I/O capacity accounting overflow")
            self._condition.notify_all()

    def _acquire_many(
        self,
        count: int,
        *,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ) -> None:
        if type(count) is not int or count <= 0:
            raise ValueError("async I/O atomic batch size must be positive")
        if count > self._max_in_flight:
            raise ValueError("async I/O atomic batch exceeds provider capacity")
        # Fast path does not allocate any cancellation subscription.
        with self._condition:
            if self._closed:
                raise RuntimeError("async I/O executor is closed")
            if self._cancelled(cancellation):
                raise TaskCancelled(cancellation.reason or "async I/O capacity wait cancelled")
            if deadline is not None and deadline.expired:
                raise TimeoutError("async I/O capacity wait deadline expired")
            if self._available >= count:
                self._available -= count
                return
        # Capacity, cancellation and close are actual condition notifications.
        # Rechecking under the same lock after subscribing prevents lost wakes.
        with wake_on_cancellation(
            cancellation,
            self._condition,
            notify_waiters=self._condition.notify_all,
        ):
            with self._condition:
                while self._available < count:
                    if self._closed:
                        raise RuntimeError("async I/O executor is closed")
                    if self._cancelled(cancellation):
                        raise TaskCancelled(cancellation.reason or "async I/O capacity wait cancelled")
                    remaining = None if deadline is None else deadline.remaining_seconds
                    if remaining is not None and remaining <= 0:
                        raise TimeoutError("async I/O capacity wait deadline expired")
                    self._condition.wait(remaining)
                if self._closed:
                    raise RuntimeError("async I/O executor is closed")
                if self._cancelled(cancellation):
                    raise TaskCancelled(cancellation.reason or "async I/O capacity wait cancelled")
                if deadline is not None and deadline.expired:
                    raise TimeoutError("async I/O capacity wait deadline expired")
                self._available -= count

    def _try_acquire_many(
        self,
        count: int,
        *,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ) -> bool:
        if type(count) is not int or count <= 0:
            raise ValueError("async I/O atomic batch size must be positive")
        if count > self._max_in_flight:
            raise ValueError("async I/O atomic batch exceeds provider capacity")
        with self._condition:
            if self._closed:
                raise RuntimeError("async I/O executor is closed")
            if self._cancelled(cancellation):
                raise TaskCancelled(
                    cancellation.reason or "async I/O capacity wait cancelled"
                )
            if deadline is not None and deadline.expired:
                raise TimeoutError("async I/O capacity wait deadline expired")
            if self._available < count:
                return False
            self._available -= count
            return True

    def _try_acquire_up_to(
        self,
        max_count: int,
        *,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ) -> int:
        if type(max_count) is not int or max_count <= 0:
            raise ValueError("async I/O maximal batch size must be positive")
        with self._condition:
            if self._closed:
                raise RuntimeError("async I/O executor is closed")
            if self._cancelled(cancellation):
                raise TaskCancelled(
                    cancellation.reason or "async I/O capacity wait cancelled"
                )
            if deadline is not None and deadline.expired:
                raise TimeoutError("async I/O capacity wait deadline expired")
            admitted = min(max_count, self._available)
            if admitted <= 0:
                return 0
            self._available -= admitted
            return admitted

    def _release_unbound_slots(self, count: int) -> None:
        with self._condition:
            self._available += count
            if self._available > self._max_in_flight:
                raise RuntimeError("async I/O capacity accounting overflow")
            self._condition.notify_all()

    @staticmethod
    def _validate_atomic_batch(
        fns: tuple[Callable[[], T], ...],
    ) -> int:
        if not isinstance(fns, tuple) or not fns:
            raise ValueError(
                "atomic async I/O batch requires a non-empty tuple"
            )
        if any(not callable(fn) for fn in fns):
            raise TypeError(
                "atomic async I/O batch entries must be callable"
            )
        return len(fns)

    def _submit_atomic_batch_reserved(
        self,
        fns: tuple[Callable[[], T], ...],
        *,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ) -> tuple[_AsyncFutureHandle[T], ...]:
        count = len(fns)
        try:
            loop = self._ensure_started()
        except BaseException:
            self._release_unbound_slots(count)
            raise
        handles = tuple(
            _AsyncFutureHandle[T](loop=loop, on_physical_done=self._release)
            for _ in fns
        )
        async def invoke(fn: Callable[[], T]) -> T:
            value = fn()
            if not inspect.isawaitable(value):
                raise TypeError(
                    "ASYNC_IO execution callable must return an awaitable"
                )
            return await value

        def start_batch() -> None:
            for handle, fn in zip(handles, fns, strict=True):
                handle.start(lambda owned=fn: invoke(owned))

        cancelled_before_dispatch = self._cancelled(cancellation)
        scheduling_failure: BaseException | None = None
        # Publishing ownership and submitting the start callback share one
        # condition cut with close(). A close that follows must enqueue its
        # shutdown after this callback; a close that wins must return slots.
        with self._condition:
            if self._closed:
                self._available += count
                if self._available > self._max_in_flight:
                    raise RuntimeError("async I/O capacity accounting overflow")
                self._condition.notify_all()
                raise RuntimeError("async I/O executor is closed")
            self._futures.update(handles)
            if cancelled_before_dispatch:
                for handle in handles:
                    handle.cancel()
            try:
                loop.call_soon_threadsafe(start_batch)
            except BaseException as exc:
                scheduling_failure = exc
        if scheduling_failure is not None:
            for handle in handles:
                handle.fail_submission(scheduling_failure)
            raise scheduling_failure
        return handles

    def submit_atomic_batch(
        self,
        fns: tuple[Callable[[], T], ...],
        *,
        deadline: Deadline | None = None,
        cancellation: CancellationTokenPort | None = None,
    ) -> tuple[_AsyncFutureHandle[T], ...]:
        count = self._validate_atomic_batch(fns)
        self._ensure_started()
        self._acquire_many(
            count,
            deadline=deadline,
            cancellation=cancellation,
        )
        return self._submit_atomic_batch_reserved(
            fns,
            deadline=deadline,
            cancellation=cancellation,
        )

    def try_submit_atomic_batch(
        self,
        fns: tuple[Callable[[], T], ...],
        *,
        deadline: Deadline | None = None,
        cancellation: CancellationTokenPort | None = None,
    ) -> tuple[_AsyncFutureHandle[T], ...] | None:
        count = self._validate_atomic_batch(fns)
        self._ensure_started()
        if not self._try_acquire_many(
            count,
            deadline=deadline,
            cancellation=cancellation,
        ):
            return None
        return self._submit_atomic_batch_reserved(
            fns,
            deadline=deadline,
            cancellation=cancellation,
        )

    def try_submit_maximal_batch(
        self,
        fns: tuple[Callable[[], T], ...],
        *,
        deadline: Deadline | None = None,
        cancellation: CancellationTokenPort | None = None,
    ) -> tuple[_AsyncFutureHandle[T], ...]:
        if not isinstance(fns, tuple) or not fns:
            raise ValueError("maximal async I/O batch requires a non-empty tuple")
        if any(not callable(fn) for fn in fns):
            raise TypeError("maximal async I/O batch entries must be callable")
        self._ensure_started()
        admitted = self._try_acquire_up_to(
            len(fns),
            deadline=deadline,
            cancellation=cancellation,
        )
        if admitted <= 0:
            return ()
        return self._submit_atomic_batch_reserved(
            fns[:admitted],
            deadline=deadline,
            cancellation=cancellation,
        )

    def submit(
        self,
        fn: Callable[..., T],
        /,
        *args: Any,
        deadline: Deadline | None = None,
        cancellation: CancellationTokenPort | None = None,
        **kwargs: Any,
    ) -> _AsyncFutureHandle[T]:
        # One physical delivery/rollback path for single and atomic batches.
        return self.submit_atomic_batch(
            (lambda: fn(*args, **kwargs),),
            deadline=deadline,
            cancellation=cancellation,
        )[0]

    def try_submit(
        self,
        fn: Callable[..., T],
        /,
        *args: Any,
        deadline: Deadline | None = None,
        cancellation: CancellationTokenPort | None = None,
        **kwargs: Any,
    ) -> _AsyncFutureHandle[T] | None:
        result = self.try_submit_atomic_batch(
            (lambda: fn(*args, **kwargs),),
            deadline=deadline,
            cancellation=cancellation,
        )
        return None if result is None else result[0]

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
        with self._condition:
            thread = self._thread
            loop = self._loop
        if thread is None or loop is None:
            return
        if thread.is_alive() and not already_closed:
            shutdown = asyncio.run_coroutine_threadsafe(self._cancel_all_tasks(), loop)
            if wait:
                try:
                    shutdown.result(timeout=self._shutdown_timeout_seconds)
                finally:
                    loop.call_soon_threadsafe(loop.stop)
            else:
                shutdown.add_done_callback(lambda _future: loop.call_soon_threadsafe(loop.stop))
        elif thread.is_alive() and wait:
            pass
        if wait:
            thread.join(timeout=self._shutdown_timeout_seconds)
            if thread.is_alive():
                raise TimeoutError("async I/O executor did not terminate")


__all__ = ["AsyncIoExecutor"]
