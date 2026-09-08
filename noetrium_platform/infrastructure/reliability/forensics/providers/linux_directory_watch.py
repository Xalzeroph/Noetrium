from __future__ import annotations

import atexit
import ctypes
import errno
import os
import select
import struct
import sys
import time
from pathlib import Path
from threading import Lock, RLock

_IN_CREATE = 0x00000100
_IN_DELETE = 0x00000200
_IN_MOVED_FROM = 0x00000040
_IN_MOVED_TO = 0x00000080
_IN_DELETE_SELF = 0x00000400
_IN_MOVE_SELF = 0x00000800
_IN_UNMOUNT = 0x00002000
_IN_Q_OVERFLOW = 0x00004000
_IN_IGNORED = 0x00008000
_INOTIFY_EVENT = struct.Struct("<iIII")
_WATCH_MASK = _IN_CREATE | _IN_DELETE | _IN_MOVED_FROM | _IN_MOVED_TO | _IN_DELETE_SELF | _IN_MOVE_SELF
_MUTATION_MASK = _WATCH_MASK | _IN_UNMOUNT | _IN_Q_OVERFLOW | _IN_IGNORED


class _LinuxInotifyHub:
    """One process-wide inotify instance with independent watch-token latches."""

    def __init__(self) -> None:
        libc = ctypes.CDLL(None, use_errno=True)
        self._add_watch = getattr(libc, "inotify_add_watch")
        self._remove_watch = getattr(libc, "inotify_rm_watch")
        init = getattr(libc, "inotify_init1")
        init.argtypes = [ctypes.c_int]
        init.restype = ctypes.c_int
        self._add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        self._add_watch.restype = ctypes.c_int
        self._remove_watch.argtypes = [ctypes.c_int, ctypes.c_int]
        self._remove_watch.restype = ctypes.c_int
        self._fd = int(init(os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)))
        if self._fd < 0:
            error = ctypes.get_errno()
            raise OSError(error, "failed to initialize Linux inotify authority")
        self._lock = RLock()
        self._read_lock = Lock()
        self._next_token = 1
        self._watch_by_token: dict[int, int] = {}
        self._tokens_by_watch: dict[int, set[int]] = {}
        self._pending: set[int] = set()
        self._closed = False
        self._owner_pid = os.getpid()

    @property
    def owner_pid(self) -> int:
        return self._owner_pid

    def _require_owner_process(self) -> None:
        if os.getpid() != self._owner_pid:
            raise OSError("Linux inotify hub cannot be reused after fork")

    def abandon_after_fork(self) -> None:
        """Detach the inherited kernel fd in a fork child without touching parent state."""
        fd, self._fd = self._fd, -1
        self._closed = True
        self._watch_by_token.clear()
        self._tokens_by_watch.clear()
        self._pending.clear()
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass

    def register(self, root: Path) -> int:
        self._require_owner_process()
        self._drain()
        with self._lock:
            watch = int(self._add_watch(self._fd, os.fsencode(root), _WATCH_MASK))
            if watch < 0:
                error = ctypes.get_errno()
                raise OSError(error, "failed to register Linux directory watch", str(root))
            token = self._next_token
            self._next_token += 1
            self._watch_by_token[token] = watch
            self._tokens_by_watch.setdefault(watch, set()).add(token)
            return token

    def _drain(self) -> None:
        """Drain non-blocking kernel events before entering the state lock."""
        self._read_lock.acquire()
        try:
            fd = self._fd
            if fd < 0:
                return
            events: list[tuple[int, int]] = []
            all_pending = False
            while True:
                try:
                    data = os.read(fd, 64 * 1024)
                except BlockingIOError:
                    break
                except OSError as exc:
                    if exc.errno == errno.EINTR:
                        continue
                    all_pending = True
                    break
                if not data:
                    break
                decoded, overflow = self._decode_events(data)
                events.extend(decoded)
                if overflow:
                    all_pending = True
                    break

            with self._lock:
                if all_pending:
                    self._pending.update(self._watch_by_token)
                for watch, mask in events:
                    if mask & _MUTATION_MASK:
                        self._pending.update(self._tokens_by_watch.get(watch, ()))
        finally:
            self._read_lock.release()

    @staticmethod
    def _decode_events(data: bytes) -> tuple[tuple[tuple[int, int], ...], bool]:
        events: list[tuple[int, int]] = []
        offset = 0
        while offset < len(data):
            if len(data) - offset < _INOTIFY_EVENT.size:
                return tuple(events), True
            watch, mask, _cookie, name_length = _INOTIFY_EVENT.unpack_from(data, offset)
            record_length = _INOTIFY_EVENT.size + name_length
            if record_length > len(data) - offset:
                return tuple(events), True
            if mask & _IN_Q_OVERFLOW:
                return tuple(events), True
            if mask & _MUTATION_MASK:
                events.append((watch, mask))
            offset += record_length
        return tuple(events), False

    def changed(self, token: int) -> bool:
        self._require_owner_process()
        self._drain()
        with self._lock:
            if token not in self._watch_by_token:
                raise OSError("Linux directory watch token is closed")
            return token in self._pending

    def wait_changed(self, token: int, timeout_seconds: float) -> bool:
        self._require_owner_process()
        deadline = time.monotonic() + timeout_seconds
        while True:
            self._drain()
            with self._lock:
                if token not in self._watch_by_token:
                    raise OSError("Linux directory watch token is closed")
                if token in self._pending:
                    return True
                fd = self._fd
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                readable, _, _ = select.select((fd,), (), (), remaining)
            except InterruptedError:
                continue
            except OSError:
                with self._lock:
                    self._pending.add(token)
                return True
            if not readable:
                self._drain()
                with self._lock:
                    return token in self._pending

    def acknowledge(self, token: int) -> None:
        self._require_owner_process()
        self._drain()
        with self._lock:
            if token not in self._watch_by_token:
                raise OSError("Linux directory watch token is closed")
            self._pending.discard(token)

    def unregister(self, token: int) -> None:
        self._require_owner_process()
        with self._lock:
            watch = self._watch_by_token.pop(token, None)
            self._pending.discard(token)
            if watch is None:
                return
            tokens = self._tokens_by_watch.get(watch)
            if tokens is None:
                return
            tokens.discard(token)
            if tokens:
                return
            self._tokens_by_watch.pop(watch, None)
            fd = self._fd

        result = int(self._remove_watch(fd, watch))
        if result < 0:
            error = ctypes.get_errno()
            if error not in (errno.EINVAL, errno.EBADF):
                raise OSError(error, "failed to remove Linux directory watch")
        # rm_watch queues IN_IGNORED. Drain it before a future registration can
        # reuse the descriptor and accidentally attribute the stale event.
        self._drain()

    def close(self) -> None:
        if os.getpid() != self._owner_pid:
            self.abandon_after_fork()
            return
        with self._lock:
            if self._closed:
                return
            self._closed = True
            fd, self._fd = self._fd, -1
            self._watch_by_token.clear()
            self._tokens_by_watch.clear()
            self._pending.clear()
        if fd >= 0:
            os.close(fd)


_HUB_LOCK = RLock()
_HUB: _LinuxInotifyHub | None = None


def _after_fork_child() -> None:
    """A fork child must never consume events from the parent's inotify instance."""
    global _HUB_LOCK, _HUB
    inherited = _HUB
    _HUB_LOCK = RLock()
    _HUB = None
    if inherited is not None:
        inherited.abandon_after_fork()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork_child)


def _hub() -> _LinuxInotifyHub:
    global _HUB
    with _HUB_LOCK:
        if _HUB is not None and _HUB.owner_pid != os.getpid():
            _HUB.abandon_after_fork()
            _HUB = None
        if _HUB is None:
            _HUB = _LinuxInotifyHub()
            atexit.register(_HUB.close)
        return _HUB


def _discard_empty_hub(hub: _LinuxInotifyHub) -> None:
    global _HUB
    with _HUB_LOCK:
        if _HUB is not hub:
            return
        with hub._lock:
            if hub._watch_by_token:
                return
        hub.close()
        _HUB = None


class LinuxDirectoryWatch:
    def __init__(self, root: Path) -> None:
        hub = _hub()
        try:
            token = hub.register(root)
        except BaseException:
            # A failed first registration must not leave an inotify fd alive.
            _discard_empty_hub(hub)
            raise
        self._hub = hub
        self._token: int | None = token

    def changed(self) -> bool:
        if self._token is None:
            raise OSError("Linux directory watch is closed")
        return self._hub.changed(self._token)

    def wait_changed(self, timeout_seconds: float) -> bool:
        if self._token is None:
            raise OSError("Linux directory watch is closed")
        return self._hub.wait_changed(self._token, timeout_seconds)

    def acknowledge(self) -> None:
        if self._token is None:
            raise OSError("Linux directory watch is closed")
        self._hub.acknowledge(self._token)

    def close(self) -> None:
        token, self._token = self._token, None
        if token is not None:
            self._hub.unregister(token)


def open_linux_directory_watch(root: Path) -> LinuxDirectoryWatch | None:
    if not sys.platform.startswith("linux"):
        return None
    return LinuxDirectoryWatch(root)


__all__ = ["LinuxDirectoryWatch", "open_linux_directory_watch"]
