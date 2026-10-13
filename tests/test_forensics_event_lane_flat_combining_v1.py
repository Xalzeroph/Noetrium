from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
import time
import unittest
from unittest import mock

from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.foundation.kernel.record_plane import event_record
from noetrium_platform.infrastructure.reliability.forensics.runtime import phase_trace as phase_trace_module
from noetrium_platform.infrastructure.reliability.forensics.runtime.phase_trace import CausalPhaseTrace
from noetrium_platform.infrastructure.reliability.forensics.runtime.write_lanes import EventWriteLane


class _Ledger:
    def __init__(self) -> None:
        self.documents: list[dict[str, object]] = []

    def append(self, document: dict[str, object]) -> str:
        self.documents.append(document)
        return f"row-{len(self.documents)}"

    @property
    def cached_tail(self) -> tuple[int, str]:
        rows = len(self.documents)
        return rows, f"row-{rows}"


class _Index:
    def __init__(self) -> None:
        self.batches: list[tuple[tuple[object, int, str], ...]] = []

    def project_events_batch(self, items) -> None:
        self.batches.append(items)


class _BlockingActor:
    actor_id = "flat-combining-test"

    def __init__(self) -> None:
        self.calls = 0
        self._lock = Lock()
        self.entered = Event()
        self.release = Event()

    def call(self, operation, fn, /, *args, **kwargs):
        del operation
        with self._lock:
            self.calls += 1
        self.entered.set()
        if not self.release.wait(5.0):
            raise TimeoutError("test actor release timed out")
        return fn(*args, **kwargs)


class _PostDrainFailureActor:
    actor_id = "post-drain-failure-test"

    def __init__(self) -> None:
        self.calls = 0
        self._serial = Lock()
        self.after_first_drain = Event()
        self.release_first = Event()

    def call(self, operation, fn, /, *args, **kwargs):
        del operation
        with self._serial:
            self.calls += 1
            call = self.calls
            result = fn(*args, **kwargs)
            if call == 1:
                self.after_first_drain.set()
                if not self.release_first.wait(5.0):
                    raise TimeoutError("post-drain failure release timed out")
                raise RuntimeError("synthetic post-drain actor failure")
            return result


class _EventStore:
    def __init__(self) -> None:
        self.events = []

    def append_event(self, event):
        self.events.append(event)
        return event.unit_digest


class EventWriteLaneFlatCombiningTests(unittest.TestCase):
    def test_concurrent_appends_share_one_actor_drain(self) -> None:
        ledger = _Ledger()
        index = _Index()
        actor = _BlockingActor()
        lane = EventWriteLane(ledger, index, batch_size=4, actor=actor)
        context = ExecutionContext("run", "trace", "span")
        callers = 16
        ready = Barrier(callers)

        def append_one(i: int) -> str:
            ready.wait()
            return lane.append(event_record(f"event-{i}", "phase", context, "component"))

        with ThreadPoolExecutor(max_workers=callers) as pool:
            futures = tuple(pool.submit(append_one, i) for i in range(callers))
            self.assertTrue(actor.entered.wait(5.0))
            deadline = time.monotonic() + 5.0
            while True:
                with lane._pending_lock:
                    pending = len(lane._pending)
                if pending == callers or time.monotonic() >= deadline:
                    break
                time.sleep(0.001)
            self.assertEqual(pending, callers)
            actor.release.set()
            row_hashes = tuple(future.result(timeout=5.0) for future in futures)

        self.assertEqual(actor.calls, 1)
        self.assertEqual(len(ledger.documents), callers)
        self.assertEqual(len(set(row_hashes)), callers)
        self.assertEqual(len(index.batches), callers // 4)
        self.assertEqual(lane.backlog(), 0)

    def test_old_generation_failure_cannot_abort_new_drain(self) -> None:
        ledger = _Ledger()
        actor = _PostDrainFailureActor()
        lane = EventWriteLane(ledger, _Index(), batch_size=32, actor=actor)
        context = ExecutionContext("run", "trace", "span")
        first = event_record("event-first", "phase", context, "component")
        second = event_record("event-second", "phase", context, "component")

        with ThreadPoolExecutor(max_workers=2) as pool:
            first_result = pool.submit(lane.append, first)
            self.assertTrue(actor.after_first_drain.wait(5.0))
            second_result = pool.submit(lane.append, second)
            deadline = time.monotonic() + 5.0
            while True:
                with lane._pending_lock:
                    pending = len(lane._pending)
                    generation = lane._active_drain
                if pending == 1 and generation == 2:
                    break
                if time.monotonic() >= deadline:
                    self.fail(
                        f"new drain did not fence itself: pending={pending} "
                        f"generation={generation}"
                    )
                time.sleep(0.001)
            actor.release_first.set()
            self.assertEqual(first_result.result(timeout=5.0), "row-1")
            self.assertEqual(second_result.result(timeout=5.0), "row-2")

        self.assertEqual(actor.calls, 2)
        self.assertEqual(len(ledger.documents), 2)


class CausalPhaseTraceHotPathTests(unittest.TestCase):
    def test_execution_context_payload_is_encoded_once_per_trace(self) -> None:
        store = _EventStore()
        context = ExecutionContext("run", "trace", "span")
        encoder = phase_trace_module.execution_context_payload

        with mock.patch.object(
            phase_trace_module,
            "execution_context_payload",
            wraps=encoder,
        ) as encode:
            trace = CausalPhaseTrace(
                store,
                context=context,
                authority_domain="test.authority",
                component_id="test.component",
                subject="test.subject",
            )
            phase = trace.start("operation")
            trace.complete(phase)

        self.assertEqual(encode.call_count, 1)
        self.assertEqual(len(store.events), 2)


if __name__ == "__main__":
    unittest.main()
