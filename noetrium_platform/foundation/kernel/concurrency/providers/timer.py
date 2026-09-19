from __future__ import annotations

from dataclasses import dataclass, field
import heapq
from threading import Condition, Thread
import time
from typing import Callable

from noetrium_platform.foundation.kernel.concurrency.api import Deadline, ScheduledTaskHandlePort, ScheduledTaskSpec


class ScheduledTaskFailed(RuntimeError):
    pass


@dataclass(order=True, slots=True)
class _Entry:
    due: float
    sequence: int
    task_id: str = field(compare=False)
    interval: float | None = field(compare=False)
    callback: Callable[[], None] = field(compare=False)
    cancelled: bool = field(default=False, compare=False)
    failure: BaseException | None = field(default=None, compare=False)
    in_heap: bool = field(default=True, compare=False)


class _Handle(ScheduledTaskHandlePort):
    def __init__(self, scheduler: "HeapTimerScheduler", entry: _Entry) -> None:
        self._scheduler = scheduler
        self._entry = entry
    @property
    def task_id(self) -> str: return self._entry.task_id
    def cancel(self) -> None: self._scheduler._cancel(self._entry)
    def assert_healthy(self) -> None:
        failure = self._entry.failure
        if failure is not None:
            raise ScheduledTaskFailed(f"scheduled task failed: {self._entry.task_id}: {type(failure).__name__}: {failure}") from failure


class HeapTimerScheduler:
    """One owned timer thread for arbitrarily many periodic registrations."""

    def __init__(self, *, name: str = "platform-timer", shutdown_timeout_seconds: float = 30.0) -> None:
        if shutdown_timeout_seconds <= 0:
            raise ValueError("timer shutdown timeout must be positive")
        self._shutdown_timeout_seconds = float(shutdown_timeout_seconds)
        self._condition = Condition()
        self._heap: list[_Entry] = []
        self._sequence = 0
        self._closed = False
        self._tasks: dict[str, _Entry] = {}
        self._seen_task_ids: set[str] = set()
        self._cancelled_tombstones = 0
        self._thread = Thread(target=self._run, name=name, daemon=False)
        self._thread.start()

    @property
    def active_registration_count(self) -> int:
        """Return the number of live timer registrations.

        This is provider observability, not a scheduling control seam. It is useful
        for governance/tests to prove that group-owned deadlines are represented by
        one timer regardless of child count.
        """

        with self._condition:
            return len(self._tasks)

    def _register(
        self,
        *,
        task_id: str,
        delay_seconds: float,
        interval_seconds: float | None,
        callback: Callable[[], None],
    ) -> ScheduledTaskHandlePort:
        task_id = str(task_id).strip()
        if not task_id:
            raise ValueError("scheduled task id required")
        if delay_seconds < 0:
            raise ValueError("scheduled task delay cannot be negative")
        if interval_seconds is not None and interval_seconds <= 0:
            raise ValueError("scheduled task interval must be positive")
        with self._condition:
            if self._closed:
                raise RuntimeError("timer scheduler is closed")
            if task_id in self._seen_task_ids:
                raise ValueError(f"scheduled task id already owned for scheduler lifetime: {task_id}")
            self._seen_task_ids.add(task_id)
            self._sequence += 1
            entry = _Entry(
                time.monotonic() + delay_seconds,
                self._sequence,
                task_id,
                interval_seconds,
                callback,
            )
            self._tasks[task_id] = entry
            heapq.heappush(self._heap, entry)
            self._condition.notify()
        return _Handle(self, entry)

    def schedule_once(
        self,
        task_id: str,
        delay_seconds: float,
        callback: Callable[[], None],
    ) -> ScheduledTaskHandlePort:
        return self._register(
            task_id=task_id,
            delay_seconds=delay_seconds,
            interval_seconds=None,
            callback=callback,
        )

    def schedule_fixed_delay(self, spec: ScheduledTaskSpec, callback: Callable[[], None]) -> ScheduledTaskHandlePort:
        return self._register(
            task_id=spec.task_id,
            delay_seconds=spec.initial_delay_seconds,
            interval_seconds=spec.interval_seconds,
            callback=callback,
        )

    def _cancel(self, entry: _Entry) -> None:
        with self._condition:
            if entry.cancelled:
                return
            entry.cancelled = True
            if entry.in_heap:
                self._cancelled_tombstones += 1
            self._tasks.pop(entry.task_id, None)
            self._maybe_compact_heap_locked()
            self._condition.notify()

    def _maybe_compact_heap_locked(self) -> None:
        """Bound lazy-cancellation memory without making every cancel O(N).

        Algorithm-Complexity: amortized O(log N) cancellation
        Algorithm-Rationale: heap rebuild occurs only after at least 64 tombstones and when cancelled entries exceed half of the heap, so each rebuild removes a proportional amount of dead state.
        """

        if self._cancelled_tombstones < 64:
            return
        if self._cancelled_tombstones * 2 <= len(self._heap):
            return
        live: list[_Entry] = []
        for item in self._heap:
            if item.cancelled:
                item.in_heap = False
            else:
                live.append(item)
        heapq.heapify(live)
        self._heap = live
        self._cancelled_tombstones = 0

    def _take_due_entry_locked(self, now: float) -> tuple[_Entry | None, float | None]:
        """Return one due task or the bounded wait until the next task.

        The caller owns ``self._condition``. Cancelled heap tombstones are removed
        lazily so cancellation remains O(1) while scheduler work is amortized over
        the entries that actually leave the heap.

        Algorithm-Complexity: O(N log N)
        Algorithm-Rationale: Each cancelled entry is popped from the heap at most once; heap pops are logarithmic and no nested traversal multiplies the number of scheduled entries.
        """

        while self._heap and self._heap[0].cancelled:
            removed = heapq.heappop(self._heap)
            if removed.in_heap:
                removed.in_heap = False
                self._cancelled_tombstones = max(0, self._cancelled_tombstones - 1)
        if not self._heap:
            return None, None
        entry = self._heap[0]
        delay = entry.due - now
        if delay > 0:
            return None, delay
        due = heapq.heappop(self._heap)
        due.in_heap = False
        return due, 0.0

    def _run(self) -> None:
        while True:
            with self._condition:
                if self._closed:
                    return
                entry, delay = self._take_due_entry_locked(time.monotonic())
                if entry is None:
                    self._condition.wait(delay)
                    continue
            if entry.cancelled:
                continue
            try:
                entry.callback()
            except BaseException as exc:
                with self._condition:
                    entry.failure = exc
                    entry.cancelled = True
                    self._tasks.pop(entry.task_id, None)
                    self._condition.notify_all()
                continue
            with self._condition:
                if entry.interval is None:
                    entry.cancelled = True
                    self._tasks.pop(entry.task_id, None)
                elif not entry.cancelled and not self._closed:
                    self._sequence += 1
                    entry.sequence = self._sequence
                    entry.due = time.monotonic() + entry.interval
                    entry.in_heap = True
                    heapq.heappush(self._heap, entry)

    def close(self, *, deadline: Deadline | None = None) -> None:
        with self._condition:
            if not self._closed:
                self._closed = True
                for entry in self._tasks.values():
                    entry.cancelled = True
                    entry.in_heap = False
                self._tasks.clear()
                self._heap.clear()
                self._cancelled_tombstones = 0
                self._condition.notify_all()
        # Every caller joins the owned thread. A second close racing the first may
        # not report success merely because the closed flag was already published.
        effective = deadline or Deadline.after(self._shutdown_timeout_seconds)
        self._thread.join(timeout=effective.remaining_seconds)
        if self._thread.is_alive():
            raise TimeoutError("timer scheduler did not terminate before deadline")
