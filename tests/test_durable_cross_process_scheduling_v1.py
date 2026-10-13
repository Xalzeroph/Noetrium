"""One cross-process VTC/LAS history, not per-run fairness counters."""
from __future__ import annotations

import subprocess
import sys
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time

import pytest

from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import (
    DurableUnifiedSchedulingAuthority,
)
from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import durable as durable_runtime
from noetrium_platform.foundation.kernel.concurrency.scheduling.api import (
    ExecutionPriority, SchedulingCandidate,
)


def _candidate(ticket: int, tenant: str) -> SchedulingCandidate:
    return SchedulingCandidate(
        ticket=ticket, group_id="flow-" + tenant,
        flow_id="flow-" + tenant, tenant_id=tenant,
        priority=ExecutionPriority.NORMAL,
        enqueued_monotonic=2.0,
    )


def test_remote_service_is_visible_to_another_process(tmp_path) -> None:
    path = tmp_path / "authority.sqlite"
    owner = DurableUnifiedSchedulingAuthority(path)
    remote = """
import sys
from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import DurableUnifiedSchedulingAuthority
s=DurableUnifiedSchedulingAuthority(sys.argv[1])
seq=s.record_grant(tenant_id="paper-a",flow_id="a",reserved_service_quanta=101)
s.record_completion(tenant_id="paper-a",flow_id="a",service_quanta=101,reserved_service_quanta=101)
print(seq)
"""
    completed = subprocess.run(
        [sys.executable, "-c", remote, str(path)],
        capture_output=True, check=True, text=True, timeout=20,
    )
    assert int(completed.stdout.strip()) == 1
    assert owner.select(
        (_candidate(1, "paper-a"), _candidate(2, "paper-b")),
        now_monotonic=3,
    ) == 2
    assert DurableUnifiedSchedulingAuthority(path).select(
        (_candidate(1, "paper-a"), _candidate(2, "paper-b")),
        now_monotonic=3,
    ) == 2


def test_grant_and_completion_are_linearized_across_processes(tmp_path) -> None:
    path = tmp_path / "authority.sqlite"
    owner = DurableUnifiedSchedulingAuthority(path)

    script = """
import sys
from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import DurableUnifiedSchedulingAuthority
s=DurableUnifiedSchedulingAuthority(sys.argv[1])
for index in range(15):
    s.record_grant(tenant_id=sys.argv[2],flow_id=sys.argv[2]+str(index),reserved_service_quanta=2)
    s.record_completion(tenant_id=sys.argv[2],flow_id=sys.argv[2]+str(index),service_quanta=2,reserved_service_quanta=2)
"""
    with ThreadPoolExecutor(max_workers=3) as pool:
        processes = [pool.submit(
            subprocess.run, [sys.executable, "-c", script, str(path), f"paper-{k}"],
            capture_output=True, text=True, timeout=40,
        ) for k in range(3)]
        for process in processes:
            result = process.result(timeout=45)
            assert result.returncode == 0, result.stderr

    assert owner._applied == 0
    assert owner.select(
        tuple(_candidate(i+1, f"paper-{i}") for i in range(3)),
        now_monotonic=4,
    ) in (1, 2, 3)
    assert owner._applied == 90
    import sqlite3
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*), MIN(sequence), MAX(sequence) "
            "FROM unified_scheduling_events"
        ).fetchone() == (90, 1, 90)


def test_naturally_concurrent_grant_followers_share_one_durable_drain_and_replay(
    tmp_path, monkeypatch,
) -> None:
    import sqlite3

    path = tmp_path / "authority.sqlite"
    scheduler = DurableUnifiedSchedulingAuthority(path)
    grouped_transactions = 0
    original_transaction = durable_runtime.immediate_sqlite_transaction

    @contextmanager
    def counted_transaction(*args, **kwargs):
        nonlocal grouped_transactions
        if kwargs.get("label") == "global scheduling grant group":
            grouped_transactions += 1
        with original_transaction(*args, **kwargs) as conn:
            yield conn

    monkeypatch.setattr(
        durable_runtime, "immediate_sqlite_transaction", counted_transaction
    )
    entered = Event()
    proceed = Event()
    original_read_cut = scheduler._read_cut

    def hold_first_read():
        if not entered.is_set():
            entered.set()
            assert proceed.wait(2.0)
        return original_read_cut()

    monkeypatch.setattr(scheduler, "_read_cut", hold_first_read)
    with ThreadPoolExecutor(max_workers=16) as pool:
        leader = pool.submit(
            scheduler.record_grant, tenant_id="paper", flow_id="flow-0"
        )
        assert entered.wait(1.0)
        followers = [
            pool.submit(
                scheduler.record_grant,
                tenant_id="paper",
                flow_id=f"flow-{index}",
            )
            for index in range(1, 16)
        ]
        deadline = time.monotonic() + 1.0
        queued = 0
        while time.monotonic() < deadline:
            with scheduler._transition_lock:
                queued = len(scheduler._transition_queue)
            if queued == 16:
                break
            time.sleep(0.001)
        assert queued == 16
        proceed.set()
        results = [leader.result(timeout=3.0)] + [
            future.result(timeout=3.0) for future in followers
        ]

    assert sorted(results) == list(range(1, 17))
    assert grouped_transactions == 1
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM unified_scheduling_events WHERE operation='grant'"
        ).fetchone()[0] == 16
    cold = DurableUnifiedSchedulingAuthority(path)
    assert cold.service_revision() == 16
    assert sum(state.in_flight for state in cold._flow_states.values()) == 16


def test_grouped_grant_logical_rejection_does_not_poison_valid_follower(
    tmp_path, monkeypatch,
) -> None:
    path = tmp_path / "authority.sqlite"
    scheduler = DurableUnifiedSchedulingAuthority(path)
    scheduler.record_grant(tenant_id="paper", flow_id="retiring")
    scheduler.release_flow("retiring", tenant_id="paper")

    entered = Event()
    proceed = Event()
    original_read_cut = scheduler._read_cut

    def hold_leader_read():
        if not entered.is_set():
            entered.set()
            assert proceed.wait(2.0)
        return original_read_cut()

    monkeypatch.setattr(scheduler, "_read_cut", hold_leader_read)
    with ThreadPoolExecutor(max_workers=3) as pool:
        leader = pool.submit(
            scheduler.record_grant, tenant_id="paper", flow_id="leader"
        )
        assert entered.wait(1.0)
        rejected = pool.submit(
            scheduler.record_grant, tenant_id="paper", flow_id="retiring"
        )
        valid = pool.submit(
            scheduler.record_grant, tenant_id="paper", flow_id="valid"
        )
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            with scheduler._transition_lock:
                if len(scheduler._transition_queue) == 3:
                    break
            time.sleep(0.001)
        with scheduler._transition_lock:
            assert len(scheduler._transition_queue) == 3
        proceed.set()
        assert leader.result(timeout=3.0) > 0
        with pytest.raises(RuntimeError, match="retiring scheduling flow"):
            rejected.result(timeout=3.0)
        assert valid.result(timeout=3.0) > 0

    cold = DurableUnifiedSchedulingAuthority(path)
    cold._read_cut()
    assert cold._flow_states[
        cold._flow_key("paper", None, "retiring")
    ].in_flight == 1
    assert cold._flow_states[
        cold._flow_key("paper", None, "valid")
    ].in_flight == 1


def test_failed_completion_cannot_mutate_durable_scheduler_cut(tmp_path) -> None:
    path = tmp_path / "authority.sqlite"
    scheduler = DurableUnifiedSchedulingAuthority(path)
    with pytest.raises(RuntimeError, match="no active flow"):
        scheduler.record_completion(
            tenant_id="paper", flow_id="not-admitted",
            service_quanta=1,
        )
    another = DurableUnifiedSchedulingAuthority(path)
    assert another.record_grant(tenant_id="paper", flow_id="run") == 1
    another.rollback_grant(tenant_id="paper", flow_id="run")
    scheduler.record_grant(tenant_id="paper", flow_id="next-run")
    scheduler.record_completion(tenant_id="paper", flow_id="next-run", service_quanta=9)
    assert scheduler.select(
        (_candidate(1, "paper"), _candidate(2, "untested")),
        now_monotonic=3,
    ) == 2


def test_local_selection_read_cut_is_not_shared_across_threads(
    monkeypatch, tmp_path,
) -> None:
    """The read-in-progress optimization belongs to one caller, not instance."""
    from threading import Event, Thread
    from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime.unified import (
        UnifiedSchedulingAuthority,
    )

    scheduler = DurableUnifiedSchedulingAuthority(tmp_path / "authority.sqlite")
    entered = Event()
    resume = Event()
    other_finished = Event()
    selected = []
    failed: list[BaseException] = []
    original = UnifiedSchedulingAuthority.select

    def pause_select(self, candidates, *, now_monotonic):
        entered.set()
        assert resume.wait(3)
        return original(self, candidates, now_monotonic=now_monotonic)

    monkeypatch.setattr(UnifiedSchedulingAuthority, "select", pause_select)

    def select_one():
        try:
            selected.append(scheduler.select((_candidate(1, "a"),), now_monotonic=3))
        except BaseException as exc:
            failed.append(exc)

    def evaluate_other_thread():
        try:
            assert not getattr(scheduler._read_scope, "inside", False)
            scheduler.ordering_key(_candidate(2, "b"), now_monotonic=3)
        except BaseException as exc:
            failed.append(exc)
        finally:
            other_finished.set()

    first = Thread(target=select_one, daemon=True)
    second = Thread(target=evaluate_other_thread, daemon=True)
    first.start()
    try:
        assert entered.wait(2)
        second.start()
        assert not other_finished.wait(0.1), (
            "ordering_key escaped the serialization cut of an active select"
        )
    finally:
        resume.set()
        first.join(3)
        if second.ident is not None:
            second.join(3)
    assert not first.is_alive()
    assert not second.is_alive()
    assert not failed
    assert selected == [1]


def test_one_full_select_does_not_reopen_cursor_for_each_candidate(
    monkeypatch, tmp_path,
) -> None:
    scheduler = DurableUnifiedSchedulingAuthority(tmp_path / "authority.sqlite")
    from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import (
        durable,
    )

    reads = 0
    original = durable.sqlite_read_snapshot

    def count_physical_reads(*args, **kwargs):
        nonlocal reads
        reads += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(durable, "sqlite_read_snapshot", count_physical_reads)
    candidates = tuple(_candidate(i, f"paper-{i}") for i in range(1, 33))
    assert scheduler.select(candidates, now_monotonic=4) in range(1, 33)
    # The one internal _read_cut invocation per candidate is a guarded no-op.
    # Exactly one fresh SQLite snapshot is opened for the whole selection.
    assert reads == 1


def test_same_environment_flow_name_across_runs_is_not_parent_drift(tmp_path) -> None:
    """The v46 failure: stable local environment IDs reused by two projects."""
    path = tmp_path / "shared-authority.sqlite"
    scheduler = DurableUnifiedSchedulingAuthority(path)
    repeated = "research-environment-lifecycle:41268eb37aa661c118142cdf"
    scheduler.record_grant(
        tenant_id="paper-one", resource_id="minecraft",
        flow_id=repeated,
    )
    scheduler.record_completion(
        tenant_id="paper-one", resource_id="minecraft",
        flow_id=repeated, service_quanta=5,
    )
    scheduler.release_flow(
        repeated, tenant_id="paper-one", resource_id="minecraft",
    )
    script = """
import sys
from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import DurableUnifiedSchedulingAuthority
s = DurableUnifiedSchedulingAuthority(sys.argv[1])
s.record_grant(tenant_id="paper-two", resource_id="minecraft", flow_id=sys.argv[2])
s.record_completion(tenant_id="paper-two", resource_id="minecraft", flow_id=sys.argv[2], service_quanta=2)
s.release_flow(sys.argv[2], tenant_id="paper-two", resource_id="minecraft")
"""
    run = subprocess.run(
        [sys.executable, "-c", script, str(path), repeated],
        capture_output=True, text=True, timeout=20,
    )
    assert run.returncode == 0, run.stderr
    scheduler._read_cut()
    first = scheduler._flow_states[
        scheduler._flow_key("paper-one", "minecraft", repeated)
    ]
    second = scheduler._flow_states[
        scheduler._flow_key("paper-two", "minecraft", repeated)
    ]
    assert first is not second
    assert first.service_quanta == 5
    assert second.service_quanta == 2
    assert first.retire_requested and second.retire_requested



def test_cold_scheduler_recovery_streams_committed_journal_rows(tmp_path) -> None:
    """Replay cannot call fetchall() on an unbounded committed event log."""
    from noetrium_platform.foundation.kernel.kernel.durability.sqlite import (
        durable_sqlite_reader,
    )

    path = tmp_path / "authority.sqlite"
    writer = DurableUnifiedSchedulingAuthority(path)
    for i in range(28):
        writer.record_grant(
            tenant_id="tenant-" + str(i % 3),
            flow_id="flow-" + str(i),
            reserved_service_quanta=5,
        )
        writer.record_completion(
            tenant_id="tenant-" + str(i % 3),
            flow_id="flow-" + str(i),
            reserved_service_quanta=5,
            service_quanta=5,
        )

    follower = DurableUnifiedSchedulingAuthority(path)

    class _Cursor:
        def __init__(self, cursor):
            self._cursor = cursor

        def __iter__(self):
            return iter(self._cursor)

        def fetchall(self):
            raise AssertionError("unbounded fetchall forbidden in recovery")

    class _Connection:
        def __init__(self, conn):
            self._conn = conn

        def execute(self, *args):
            return _Cursor(self._conn.execute(*args))

    with durable_sqlite_reader(path, timeout_seconds=3) as conn:
        follower._catch_up(_Connection(conn))

    assert follower._applied == 56
    assert follower.select(
        (_candidate(1, "tenant-0"), _candidate(2, "never-run")),
        now_monotonic=3,
    ) == 2



def test_authority_bulk_unit_ordering_uses_one_coherent_read_cut(
    monkeypatch, tmp_path,
) -> None:
    """Bulk ordering is semantically identical but reads durable state once."""
    from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import (
        durable,
    )

    authority = DurableUnifiedSchedulingAuthority(tmp_path / "batch-order.sqlite")
    authority.record_grant(
        tenant_id="paper-a", flow_id="flow-paper-a",
        reserved_service_quanta=9,
    )
    authority.record_completion(
        tenant_id="paper-a", flow_id="flow-paper-a",
        service_quanta=9, reserved_service_quanta=9,
    )
    candidates = tuple(_candidate(index, f"paper-{index}") for index in range(1, 65))
    reads = 0
    reader = durable.sqlite_read_snapshot

    def instrumented_reader(*args, **kwargs):
        nonlocal reads
        reads += 1
        return reader(*args, **kwargs)

    monkeypatch.setattr(durable, "sqlite_read_snapshot", instrumented_reader)
    keys = authority.ordering_keys(candidates, now_monotonic=5.0)
    assert reads == 1
    assert len(keys) == len(candidates)
    assert keys == tuple(
        authority.ordering_key(candidate, now_monotonic=5.0)
        for candidate in candidates
    )
    assert reads == len(candidates) + 1
