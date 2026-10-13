"""Cross-process Resource Authority commit notifications are hints from durable Event truth."""
from __future__ import annotations

from threading import Event, Thread
import sqlite3
import subprocess
import sys
import time

from model_admission_test_support import make_model_admission_registry
from noetrium_platform.infrastructure.resources.authority import UniversalResourceAuthority
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
from noetrium_platform.infrastructure.resources.authority.runtime.commit_feed import (
    SQLiteAuthorityCommitFeed, _SQLiteFileWake,
)
from noetrium_platform.foundation.kernel.kernel.durability.sqlite import (
    durable_sqlite_reader,
)


def _feed(path):
    runtime = build_concurrency_runtime(
        budget=ConcurrencyBudget(
            max_blocking_io_workers=2,
            max_cpu_workers=1,
            default_queue_capacity=4,
        ),
    )
    group = runtime.open_task_group("authority-commit-feed-test")

    def close_group(owned):
        owned.close()
        runtime.close()

    return SQLiteAuthorityCommitFeed(
        path, task_group=group, close_group=close_group,
    )


def test_readonly_sqlite_close_does_not_self_wake_file_watcher(tmp_path) -> None:
    """A cursor read must not manufacture a commit-feed wake from WAL close."""
    import pytest

    if sys.platform != "linux":
        pytest.skip("inotify regression is Linux-specific")
    path = tmp_path / "reader-wake.sqlite"
    writer = sqlite3.connect(path)
    wake = None
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE rows(value INTEGER)")
        writer.commit()
        wake = _SQLiteFileWake(path)
        with durable_sqlite_reader(path, timeout_seconds=2) as conn:
            assert conn.execute("SELECT COUNT(*) FROM rows").fetchone() == (0,)

        started = time.monotonic()
        wake.wait(0.05)
        elapsed = time.monotonic() - started
        assert elapsed >= 0.03, (
            "read-only SQLite close spuriously woke the commit feed",
            elapsed,
        )
    finally:
        if wake is not None:
            wake.close()
        writer.close()


def test_external_process_release_is_seen_from_committed_authority_event(tmp_path) -> None:
    registry = make_model_admission_registry()
    controller = registry.controller_for(
        deployment_id="one", deployment_generation="c" * 64,
        qualified_capacity=1,
    )
    lease = controller.acquire(owner_id="paper")
    feed = _feed(registry._test_authority.path)
    observed = Event()
    unsubscribe = feed.subscribe(
        frozenset({controller._resource_key}), observed.set,
    )
    try:
        assert not observed.wait(0.05)
        subprocess.run(
            [
                sys.executable, "-c",
                "import sys; from noetrium_platform.infrastructure.resources.authority "
                "import UniversalResourceAuthority; "
                "UniversalResourceAuthority(sys.argv[1]).release_claim(sys.argv[2])",
                str(registry._test_authority.path), lease.claim_id,
            ],
            check=True, timeout=20, capture_output=True,
        )
        assert observed.wait(2), "committed change lost across process boundary"
    finally:
        unsubscribe()
        feed.close()
        lease.release()
        registry.close()


def test_other_resource_changes_do_not_falsely_notify_this_domain() -> None:
    registry = make_model_admission_registry()
    a = registry.controller_for(
        deployment_id="a", deployment_generation="a" * 64,
        qualified_capacity=1,
    )
    b = registry.controller_for(
        deployment_id="b", deployment_generation="b" * 64,
        qualified_capacity=1,
    )
    first = a.acquire(owner_id="a")
    second = b.acquire(owner_id="b")
    feed = _feed(registry._test_authority.path)
    observed = Event()
    unsubscribe = feed.subscribe(frozenset({a._resource_key}), observed.set)
    try:
        second.release()
        assert not observed.wait(0.7)
        first.release()
        assert observed.wait(2)
    finally:
        unsubscribe()
        feed.close()
        first.release()
        second.release()
        registry.close()


def test_model_waiter_rechecks_authority_on_cross_process_commit() -> None:
    registry = make_model_admission_registry()
    feed = _feed(registry._test_authority.path)
    registry._change_feed = feed
    controller = registry.controller_for(
        deployment_id="observed", deployment_generation="d" * 64,
        qualified_capacity=1,
    )
    holder = controller.acquire(owner_id="holder")
    acquired = Event()
    errors: list[BaseException] = []

    def contender() -> None:
        try:
            with controller.acquire(timeout_seconds=4, owner_id="contender"):
                acquired.set()
        except BaseException as exc:
            errors.append(exc)

    thread = Thread(target=contender, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 2
        while controller.snapshot().waiting < 1 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert controller.snapshot().waiting == 1
        with subprocess.Popen(
            [
                sys.executable, "-c",
                "import sys; from noetrium_platform.infrastructure.resources.authority "
                "import UniversalResourceAuthority; "
                "UniversalResourceAuthority(sys.argv[1]).release_claim(sys.argv[2])",
                str(registry._test_authority.path), holder.claim_id,
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ) as child:
            stdout, stderr = child.communicate(timeout=20)
            assert child.returncode == 0, (stdout, stderr)
        assert acquired.wait(2)
        assert not errors
    finally:
        holder.release()
        thread.join(4)
        registry.close()


def test_feed_survives_missed_kernel_watch_by_rechecking_durable_cursor(
    monkeypatch,
) -> None:
    from noetrium_platform.infrastructure.resources.authority.runtime import commit_feed
    monkeypatch.setattr(
        commit_feed._SQLiteFileWake, "wait",
        lambda self, seconds: time.sleep(min(seconds, 0.025)),
    )
    registry = make_model_admission_registry()
    controller = registry.controller_for(
        deployment_id="no-inotify", deployment_generation="e" * 64,
        qualified_capacity=1,
    )
    holder = controller.acquire(owner_id="holder")
    feed = _feed(registry._test_authority.path)
    changed = Event()
    unsubscribe = feed.subscribe(frozenset({controller._resource_key}), changed.set)
    try:
        holder.release()
        assert changed.wait(2)
    finally:
        unsubscribe()
        feed.close()
        holder.release()
        registry.close()


def test_feed_failed_physical_join_does_not_publish_closed_or_lose_retry() -> None:
    """A stalled reader remains owned; later shutdown retries the same handle."""
    from noetrium_platform.foundation.kernel.concurrency.api import PhysicalJoinTimeout

    class _PhysicalTask:
        def __init__(self) -> None:
            self.joins = 0

        def result(self, timeout=None):
            self.joins += 1
            if self.joins == 1:
                raise PhysicalJoinTimeout("injected physical join timeout")

    task = _PhysicalTask()
    closed_groups: list[object] = []
    group = object()
    feed = SQLiteAuthorityCommitFeed(
        "unused-authority.sqlite",
        task_group=group,
        close_group=closed_groups.append,
    )
    feed._task = task
    try:
        import pytest
        with pytest.raises(PhysicalJoinTimeout):
            feed.close()
        assert feed._stop.is_set()
        assert not feed._closed
        assert not closed_groups

        feed.close()
        assert feed._closed
        assert closed_groups == [group]
        assert task.joins == 2
    finally:
        feed.close()


def test_feed_group_close_failure_remains_retryable() -> None:
    """A physically completed reader cannot waive the owning TaskGroup cut."""
    import pytest

    group = object()
    closes = []

    def close_group(g):
        closes.append(g)
        if len(closes) == 1:
            raise RuntimeError("injected TaskGroup retirement failure")

    feed = SQLiteAuthorityCommitFeed(
        "unused-authority.sqlite",
        task_group=group,
        close_group=close_group,
    )
    with pytest.raises(RuntimeError, match="TaskGroup retirement"):
        feed.close()
    assert not feed._closed
    feed.close()
    assert feed._closed
    assert closes == [group, group]


def test_feed_shutdown_cut_rejects_new_subscriptions_before_physical_join(
    monkeypatch,
) -> None:
    """A failed close is retryable but cannot accept unserviceable listeners."""
    import pytest
    from noetrium_platform.foundation.kernel.concurrency.api import PhysicalJoinTimeout

    class _DelayedTask:
        calls = 0

        def result(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise PhysicalJoinTimeout("reader has not physically stopped")

    feed = SQLiteAuthorityCommitFeed(
        "unused-authority.sqlite",
        task_group=object(),
        close_group=lambda group: None,
    )
    monkeypatch.setattr(feed, "_read_heads", lambda domains: (None,) * len(domains))
    feed._task = _DelayedTask()
    with pytest.raises(PhysicalJoinTimeout):
        feed.close()
    assert not feed._closed
    with pytest.raises(RuntimeError, match="closing"):
        feed.subscribe(frozenset({"resource"}), lambda: None)
    feed.close()
    assert feed._closed


def test_commit_cursor_chunks_at_actual_sqlite_variable_limit() -> None:
    import sqlite3

    class _Rows:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    class _Reader:
        def __init__(self):
            self.calls = []

        def getlimit(self, key):
            assert key == sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER
            return 2

        def execute(self, sql, args):
            assert "resource_authority_event_heads" in sql
            assert len(args) <= 2
            self.calls.append(tuple(args))
            return _Rows([
                (domain, "event:" + domain) for domain in args
                if domain != "domain-3"
            ])

    reader = _Reader()
    domains = tuple(f"domain-{index}" for index in range(1, 8))
    result = SQLiteAuthorityCommitFeed._heads(reader, domains)
    assert result == tuple(
        None if domain == "domain-3" else "event:" + domain
        for domain in domains
    )
    assert reader.calls == [
        ("domain-1", "domain-2"),
        ("domain-3", "domain-4"),
        ("domain-5", "domain-6"),
        ("domain-7",),
    ]
