from __future__ import annotations

from pathlib import Path

from noetrium_platform.foundation.governance.concurrency.api import ConcurrencyDocument, ConcurrencyLanguage
from noetrium_platform.foundation.governance.concurrency.composition import build_concurrency_governance
from noetrium_platform.foundation.governance.concurrency.runtime import PythonConcurrencyAnalyzer


def _analyze(text: str, path: str = "noetrium_platform/example/runtime/x.py"):
    doc = ConcurrencyDocument(path, ConcurrencyLanguage.PYTHON, "0" * 64, text)
    return PythonConcurrencyAnalyzer().analyze(doc)


def _codes(result):
    return {finding.code for hot in result.hotspots for finding in hot.findings}


def test_analyzer_rejects_unmanaged_thread_and_unbounded_queue() -> None:
    result = _analyze(
        """
import threading, queue
def f():
    q = queue.Queue()
    t = threading.Thread(target=lambda: None, daemon=True)
    t.start()
"""
    )
    assert {"unbounded-queue", "unmanaged-thread", "daemon-thread-lifecycle"} <= _codes(result)


def test_platform_concurrency_provider_is_allowed_to_own_thread() -> None:
    result = _analyze(
        """
from threading import Thread
def f():
    return Thread(target=lambda: None, daemon=False)
""",
        "noetrium_platform/foundation/kernel/concurrency/providers/example.py",
    )
    assert "unmanaged-thread" not in _codes(result)


def test_async_blocking_call_is_p0() -> None:
    result = _analyze(
        """
import time
async def f():
    time.sleep(1)
"""
    )
    assert "blocking-in-async" in _codes(result)


def test_condition_wait_is_not_classified_as_slow_io_under_lock() -> None:
    result = _analyze(
        """
from threading import Condition
class X:
    def __init__(self):
        self._condition = Condition()
    def f(self):
        with self._condition:
            self._condition.wait(timeout=1)
"""
    )
    assert "blocking-under-lock" not in _codes(result)


def test_baseline_gate_blocks_new_p0_p1(tmp_path: Path) -> None:
    source = tmp_path / "noetrium_platform" / "x.py"
    source.parent.mkdir(parents=True)
    source.write_text("def f():\n    return 1\n")
    service = build_concurrency_governance(tmp_path, state_root=tmp_path / ".state")
    service.accept_baseline()
    _snapshot, report = service.gate()
    assert report.passed
    source.write_text("import queue\ndef f():\n    return queue.Queue()\n")
    _snapshot, report = service.gate()
    assert not report.passed
    assert any("unbounded-queue" in row for row in report.blockers)


def test_blocking_under_lock_is_always_a_finding() -> None:
    result = _analyze(
        """
from threading import Lock
from pathlib import Path
def f():
    lock = Lock()
    with lock:
        Path('x').open('rb')
"""
    )
    assert "blocking-under-lock" in _codes(result)


def test_async_memory_join_is_not_classified_as_lifecycle_blocking() -> None:
    result = _analyze(
        """
async def f(chunks):
    a = b''.join(chunks)
    b = ''.join(str(item) for item in chunks)
    return a, b
"""
    )
    assert "blocking-in-async" not in _codes(result)
    assert "timeoutless-wait" not in _codes(result)


def test_async_thread_join_remains_blocking() -> None:
    result = _analyze(
        """
async def f(thread):
    thread.join()
"""
    )
    assert "blocking-in-async" in _codes(result)


def test_lock_held_call_into_local_blocking_helper_is_detected() -> None:
    result = _analyze(
        """
import os
from threading import Lock
class Writer:
    def __init__(self):
        self._lock = Lock()
    def _write_owned(self, fd, payload):
        os.write(fd, payload)
    def append(self, fd, payload):
        with self._lock:
            self._write_owned(fd, payload)
"""
    )
    assert "blocking-helper-under-lock" in _codes(result)


def test_local_blocking_helper_outside_lock_is_not_flagged_as_under_lock() -> None:
    result = _analyze(
        """
import os
class Writer:
    def _write_owned(self, fd, payload):
        os.write(fd, payload)
    def append(self, fd, payload):
        self._write_owned(fd, payload)
"""
    )
    assert "blocking-helper-under-lock" not in _codes(result)
    assert "blocking-under-lock" not in _codes(result)


def test_reviewed_bounded_fanout_contract_suppresses_only_loop_submit_warning() -> None:
    result = _analyze(
        """
def f(group, values, workers):
    \"\"\"
    Concurrency-Policy: BOUNDED_TASK_FANOUT
    Concurrency-Rationale: The active handle window is capped by the fixed worker count before each new submission is admitted.
    \"\"\"
    active = []
    for value in values:
        if len(active) >= workers:
            break
        active.append(group.submit(value))
"""
    )
    assert "executor-fanout-in-loop" not in _codes(result)
    hotspot = result.hotspots[0]
    assert hotspot.metrics.fanout_in_loops == 1


def test_awaited_process_wait_is_not_classified_as_blocking_sync_wait() -> None:
    result = _analyze(
        """
async def stop(process):
    await process.wait()
"""
    )
    codes = _codes(result)
    assert "blocking-in-async" not in codes
    assert "timeoutless-wait" not in codes


def test_concurrency_inventory_excludes_local_server_state(tmp_path: Path) -> None:
    from noetrium_platform.foundation.governance.concurrency.providers import RepositoryConcurrencySourceInventory
    from noetrium_platform.foundation.governance.providers import RepositorySourceTree
    (tmp_path / "noetrium_platform").mkdir()
    (tmp_path / ".server-state").mkdir()
    (tmp_path / "noetrium_platform" / "ok.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / ".server-state" / "foreign.py").write_text("import threading\nthreading.Thread()\n", encoding="utf-8")
    paths = [doc.relative_path for doc in RepositoryConcurrencySourceInventory(RepositorySourceTree(tmp_path)).documents()]
    assert paths == ["noetrium_platform/ok.py"]


def test_multi_hop_local_blocking_helper_chain_is_detected_under_lock() -> None:
    result = _analyze(
        """
import os
from threading import Lock
class Writer:
    def _write(self, fd, payload):
        os.write(fd, payload)
    def _encode_and_write(self, fd, payload):
        self._write(fd, payload)
    def append(self, fd, payload):
        lock = Lock()
        with lock:
            self._encode_and_write(fd, payload)
"""
    )
    assert "blocking-helper-under-lock" in _codes(result)


def test_python_analyzer_revision_remains_semantic_v10() -> None:
    assert _analyze("def f():\n    return 1\n").analyzer_revision == "python-concurrency-ast-v10"