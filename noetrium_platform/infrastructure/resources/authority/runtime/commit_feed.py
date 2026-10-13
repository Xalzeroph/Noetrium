"""Non-authoritative wakeups from already committed Resource Authority Event Units.

The durable source is resource_authority_event_heads, written in the SAME
SQLite transaction as each resource Event. inotify only reduces wake latency:
missed/coalesced notifications, WAL checkpoint, and watcher loss are recovered
by a bounded authoritative cursor recheck. Notifications never confer capacity.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import select
import sqlite3
from threading import Event, Lock
from typing import Callable
from noetrium_platform.foundation.kernel.kernel import canonical_digest, blocking_wait
from noetrium_platform.foundation.kernel.kernel.durability.sqlite import (
    durable_sqlite_reader, sqlite_read_snapshot,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    ExecutionLaneKind, ExecutionSpec, TaskFailureScope, TaskGroupPort,
)

# Observe durable SQLite changes without subscribing to IN_CLOSE_WRITE.
# SQLite read-only connections may open the WAL with a write-capable fd and
# closing that fd emits CLOSE_WRITE even when no byte changed. Watching it makes
# this feed wake itself: _read_heads() closes its reader, the WAL emits
# CLOSE_WRITE, and the next wait returns immediately forever. Real WAL commits
# emit IN_MODIFY; parent-directory move/create events cover WAL replacement.
_WATCH_MASK = (
    0x2      # IN_MODIFY
    | 0x4    # IN_ATTRIB
    | 0x40   # IN_MOVED_FROM
    | 0x80   # IN_MOVED_TO
    | 0x100  # IN_CREATE
    | 0x200  # IN_DELETE
    | 0x400  # IN_DELETE_SELF
    | 0x800  # IN_MOVE_SELF
    | 0x4000 # IN_Q_OVERFLOW
)


class _SQLiteFileWake:
    """Watch actual SQLite WAL writes, not just directory-entry changes."""

    def __init__(self, path: Path):
        self._path = path
        self._fd = -1
        self._watched: set[str] = set()
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            init = libc.inotify_init1
            init.argtypes = [ctypes.c_int]
            init.restype = ctypes.c_int
            add = libc.inotify_add_watch
            add.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
            add.restype = ctypes.c_int
            self._add = add
            self._fd = int(init(os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)))
            if self._fd >= 0:
                self._register_watches()
        except (AttributeError, OSError):
            self.close()

    def _register_watches(self) -> None:
        if self._fd < 0:
            return
        # The parent detects WAL creation/replacement and normal DB changes.
        for path in (self._path.parent, self._path, Path(str(self._path) + "-wal")):
            key = str(path)
            if not path.exists() or key in self._watched:
                continue
            wd = self._add(self._fd, os.fsencode(path), _WATCH_MASK)
            if wd >= 0:
                self._watched.add(key)

    def wait(self, seconds: float) -> None:
        if self._fd < 0:
            blocking_wait(seconds)
            return
        try:
            readable, _, _ = select.select([self._fd], [], [], seconds)
            if readable:
                while True:
                    try:
                        if not os.read(self._fd, 65536):
                            break
                    except BlockingIOError:
                        break
                # A WAL may have been recreated since the last observation.
                self._watched.clear()
                self._register_watches()
        except (OSError, ValueError):
            self.close()
            blocking_wait(seconds)

    def close(self) -> None:
        fd, self._fd = self._fd, -1
        if fd >= 0:
            os.close(fd)


class SQLiteAuthorityCommitFeed:
    """One per-process projection of a shared, transactional Authority log.

    Registration is deliberately separate from authorization; consumers MUST
    recheck Resource Authority after every wake. If a watcher is unavailable,
    the durable cursor is checked at the bounded fallback interval.
    """

    _FALLBACK_SECONDS = 0.5

    def __init__(
        self, path: str | Path, *, task_group: TaskGroupPort,
        close_group: Callable[[TaskGroupPort], None],
    ):
        self.path = Path(path).resolve()
        self._task_group = task_group
        self._close_group = close_group
        self._lock = Lock()
        self._close_lock = Lock()
        self._next_id = 1
        self._subscriptions: dict[
            int, tuple[tuple[str, ...], tuple[str | None, ...], Callable[[], None]]
        ] = {}
        self._stop = Event()
        self._task = None
        self._last_failure: BaseException | None = None
        self._closed = False

    @staticmethod
    def _domains(resource_keys: frozenset[str]) -> tuple[str, ...]:
        if not resource_keys or any(
            type(k) is not str or not k.strip() for k in resource_keys
        ):
            raise ValueError("Authority change subscription requires resource keys")
        return tuple(sorted("resource." + canonical_digest(k)[:32] for k in resource_keys))

    @staticmethod
    def _heads(
        conn: sqlite3.Connection, domains: tuple[str, ...]
    ) -> tuple[str | None, ...]:
        # SQLite's bind-variable limit varies by build and can be smaller
        # than the number of active research projects. Bound each query by
        # the actual connection capability, not a guessed platform constant.
        capacity = conn.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER)
        if capacity <= 0:
            raise RuntimeError("SQLite reports no bind capacity for Authority cursor")
        indexed: dict[str, str] = {}
        for offset in range(0, len(domains), capacity):
            chunk = domains[offset:offset + capacity]
            placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(
                "SELECT authority_domain, event_digest FROM resource_authority_event_heads "
                f"WHERE authority_domain IN ({placeholders})",
                chunk,
            ).fetchall()
            indexed.update((str(domain), str(digest)) for domain, digest in rows)
        return tuple(indexed.get(domain) for domain in domains)

    def _read_heads(self, domains: tuple[str, ...]) -> tuple[str | None, ...]:
        with durable_sqlite_reader(self.path, timeout_seconds=2) as conn:
            with sqlite_read_snapshot(conn):
                return self._heads(conn, domains)

    def subscribe(
        self, resource_keys: frozenset[str], callback: Callable[[], None]
    ) -> Callable[[], None]:
        if not callable(callback):
            raise TypeError("Authority change callback must be callable")
        domains = self._domains(resource_keys)
        baseline = self._read_heads(domains)
        with self._lock:
            if self._closed or self._stop.is_set():
                raise RuntimeError("Resource Authority commit feed is closing")
            token = self._next_id
            self._next_id += 1
            self._subscriptions[token] = (domains, baseline, callback)
            if self._task is None:
                try:
                    self._task = self._task_group.submit(
                        ExecutionSpec(
                            task_id="resource-authority-commit-observation",
                            lane_kind=ExecutionLaneKind.BLOCKING_IO,
                            failure_scope=TaskFailureScope.CALLER,
                        ),
                        lambda _context: self._run(),
                    )
                except BaseException:
                    self._subscriptions.pop(token, None)
                    raise

        def unsubscribe() -> None:
            with self._lock:
                self._subscriptions.pop(token, None)

        return unsubscribe

    def _run(self) -> None:
        wake = _SQLiteFileWake(self.path)
        try:
            while not self._stop.is_set():
                with self._lock:
                    subscribers = tuple(self._subscriptions.items())
                if subscribers:
                    domains = tuple(sorted({
                        domain for _, (group, _, _) in subscribers for domain in group
                    }))
                    try:
                        latest = self._read_heads(domains)
                    except (OSError, sqlite3.Error) as exc:
                        # Retain the failure for diagnostics, never fabricate a
                        # commit. Next bounded observation retries durable truth.
                        self._last_failure = exc
                    else:
                        heads = dict(zip(domains, latest, strict=True))
                        callbacks: list[Callable[[], None]] = []
                        with self._lock:
                            for token, (group, prior, callback) in subscribers:
                                current = self._subscriptions.get(token)
                                if current is None:
                                    continue
                                new = tuple(heads.get(domain) for domain in group)
                                if current[1] != new:
                                    self._subscriptions[token] = (
                                        group, new, callback
                                    )
                                    callbacks.append(callback)
                        for callback in callbacks:
                            try:
                                callback()
                            except Exception as exc:
                                self._last_failure = exc
                # Kernel watch is a latency optimization, NOT a durable cursor.
                wake.wait(self._FALLBACK_SECONDS)
        finally:
            wake.close()

    def close(self) -> None:
        # Keep the feed retryably owned until its physical reader and its
        # TaskGroup BOTH converge. A timed-out join must not mark it closed.
        with self._close_lock:
            with self._lock:
                if self._closed:
                    return
                self._subscriptions.clear()
                self._stop.set()
                task = self._task
            if task is not None:
                task.result(timeout=self._FALLBACK_SECONDS * 4)
            self._close_group(self._task_group)
            with self._lock:
                self._closed = True
