from __future__ import annotations

from dataclasses import replace
import unittest
from contextlib import contextmanager
from threading import RLock
from typing import Iterator

from noetrium_platform.infrastructure.lifecycle.launch_control.history import RuntimeHistory
from noetrium_platform.infrastructure.lifecycle.launch_control.runtime_state_contracts import RuntimeControlState, RuntimeTxnPhase
from noetrium_platform.infrastructure.lifecycle.launch_control.state import RuntimeControlStore
from noetrium_platform.infrastructure.lifecycle.launch_control.status_readers import RuntimeControlStatusReader


class MemoryRuntimeStateStore:
    def __init__(self) -> None:
        self.value: RuntimeControlState | None = None

    def exists(self) -> bool:
        return self.value is not None

    def read(self) -> RuntimeControlState:
        assert self.value is not None
        return self.value

    def write(self, state: RuntimeControlState) -> None:
        self.value = state

    def reference(self) -> str:
        return "memory://runtime-state"


class MemoryHistoryStorage:
    def __init__(self) -> None:
        self.rows: list[str] = []
        self._lock = RLock()

    def lines(self) -> tuple[str, ...]:
        return tuple(self.rows)

    def append(self, encoded_row: bytes) -> None:
        self.rows.extend(encoded_row.decode("utf-8").splitlines())

    def reference(self) -> str:
        return "memory://runtime-history"

    @contextmanager
    def exclusive(self) -> Iterator[object]:
        with self._lock:
            yield self


class RuntimeStorageBackendDecouplingV180Tests(unittest.TestCase):
    def test_control_and_status_need_no_filesystem_backend(self) -> None:
        state_store = MemoryRuntimeStateStore()
        history = RuntimeHistory(MemoryHistoryStorage())
        control = RuntimeControlStore(state_store, history)

        initial = control.create("ctl", "manifest")
        current = replace(initial, phase=RuntimeTxnPhase.RUNNING, current_action="verify_release")
        control.write(current)

        observation = RuntimeControlStatusReader(state_store, history).observe()
        self.assertEqual(observation.state, current)
        self.assertEqual(observation.history_errors, ())
        self.assertEqual(
            observation.evidence_refs[:2],
            ("memory://runtime-state", "memory://runtime-history"),
        )

    def test_one_control_write_performs_one_verified_history_scan(self) -> None:
        state_store = MemoryRuntimeStateStore()
        storage = MemoryHistoryStorage()
        history = RuntimeHistory(storage)
        control = RuntimeControlStore(state_store, history)

        original_lines = storage.lines
        calls = 0

        def counted_lines() -> tuple[str, ...]:
            nonlocal calls
            calls += 1
            return original_lines()

        storage.lines = counted_lines  # type: ignore[method-assign]
        control.create("ctl", "manifest")
        self.assertEqual(calls, 1)
        calls = 0
        control.write(replace(control.read(), phase=RuntimeTxnPhase.RUNNING))
        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
