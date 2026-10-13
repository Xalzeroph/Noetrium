from __future__ import annotations

import ctypes
import math
import sys
from pathlib import Path

from noetrium_platform.infrastructure.reliability.forensics.providers.linux_directory_watch import (
    LinuxDirectoryWatch,
    open_linux_directory_watch,
)


_FILE_NOTIFY_CHANGE_FILE_NAME = 0x00000001
_FILE_NOTIFY_CHANGE_DIR_NAME = 0x00000002
_FILE_NOTIFY_CHANGE_LAST_WRITE = 0x00000010
_WAIT_OBJECT_0 = 0x00000000
_WAIT_TIMEOUT = 0x00000102
_WAIT_FAILED = 0xFFFFFFFF
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


def _open_windows_directory_watch(
    root: Path, *, notify_writes: bool = False,
) -> int | None:
    if sys.platform != "win32":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    find_first = kernel32.FindFirstChangeNotificationW
    find_first.argtypes = [ctypes.c_wchar_p, ctypes.c_int, ctypes.c_uint32]
    find_first.restype = ctypes.c_void_p
    mask = _FILE_NOTIFY_CHANGE_FILE_NAME | _FILE_NOTIFY_CHANGE_DIR_NAME
    if notify_writes:
        mask |= _FILE_NOTIFY_CHANGE_LAST_WRITE
    handle = find_first(str(root), 0, mask)
    value = ctypes.cast(handle, ctypes.c_void_p).value
    if value in (None, _INVALID_HANDLE_VALUE):
        error = ctypes.get_last_error()
        raise OSError(error, "failed to open Windows directory change notification", str(root))
    return int(value)


class DirectoryChangeSignal:
    """Detect directory-entry mutations without enumerating the directory.

    Linux uses inotify and Windows uses a kernel change-notification handle.
    Hosts without one of those exact mutation authorities are unsupported and
    fail closed. The caller owns the authoritative expected signature; this
    object owns only the event cursor and a fail-closed pending bit.
    """

    def __init__(self, root: Path, *, notify_writes: bool = False) -> None:
        self.root = root
        self._linux_watch: LinuxDirectoryWatch | None = open_linux_directory_watch(
            root, notify_writes=notify_writes,
        )
        self._windows_handle = _open_windows_directory_watch(
            root, notify_writes=notify_writes,
        )
        if self._linux_watch is None and self._windows_handle is None:
            raise RuntimeError(
                "directory mutation authority requires Linux inotify or Windows change notifications"
            )
        self._pending = False
        self._close_error: OSError | None = None

    @property
    def mode(self) -> str:
        if self._linux_watch is not None:
            return "inotify"
        if self._windows_handle is not None:
            return "windows-notify"
        raise RuntimeError("directory mutation authority is unavailable")

    def _drain_events(self) -> bool:
        if self._linux_watch is None:
            return False
        try:
            return self._linux_watch.changed()
        except OSError:
            self._pending = True
            return True

    def _windows_changed(self, timeout_ms: int = 0) -> bool:
        handle = self._windows_handle
        if handle is None:
            return False
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        wait = kernel32.WaitForSingleObject
        wait.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        wait.restype = ctypes.c_uint32
        result = int(wait(ctypes.c_void_p(handle), timeout_ms))
        if result == _WAIT_OBJECT_0:
            return True
        if result == _WAIT_TIMEOUT:
            return False
        if result == _WAIT_FAILED:
            error = ctypes.get_last_error()
            raise OSError(error, "Windows directory change notification wait failed", str(self.root))
        raise OSError(f"unexpected Windows wait result: {result}")

    def changed_since(
        self,
        expected_signature: tuple[int, int, int, int] | None,
    ) -> bool:
        """Return whether an unacknowledged external mutation is observable."""
        if self._pending:
            return True
        if self._drain_events():
            self._pending = True
            return True
        if self._windows_changed():
            self._pending = True
            return True
        return False

    def wait_changed_since(
        self,
        expected_signature: tuple[int, int, int, int] | None,
        *,
        timeout_seconds: float,
        wakeup_fd: int | None = None,
    ) -> bool:
        """Await a mutation or an optional physical process-exit descriptor."""
        if isinstance(timeout_seconds, bool) or not math.isfinite(float(timeout_seconds)) or timeout_seconds < 0:
            raise ValueError("directory change wait must be finite and non-negative")
        if wakeup_fd is not None and (type(wakeup_fd) is not int or wakeup_fd < 0):
            raise ValueError("physical exit wake descriptor must be a live file descriptor")
        if self.changed_since(expected_signature) or timeout_seconds == 0:
            return self._pending
        if self._windows_handle is not None:
            if wakeup_fd is not None:
                raise RuntimeError("physical exit descriptor wake is unsupported on Windows")
            timeout_ms = min(0xFFFFFFFE, max(1, math.ceil(timeout_seconds * 1000.0)))
            if self._windows_changed(timeout_ms):
                self._pending = True
                return True
            return False
        if self._linux_watch is not None:
            try:
                if self._linux_watch.wait_changed(timeout_seconds, wakeup_fd=wakeup_fd):
                    self._pending = True
                    return True
            except OSError:
                self._pending = True
                return True
            return self._pending
        raise RuntimeError("directory mutation authority is unavailable")

    def acknowledge(self) -> None:
        """Consume mutations caused by the owning writer and clear the latch."""
        if self._linux_watch is not None:
            self._linux_watch.acknowledge()
        if self._windows_handle is not None and self._windows_changed():
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            advance = kernel32.FindNextChangeNotification
            advance.argtypes = [ctypes.c_void_p]
            advance.restype = ctypes.c_int
            if not advance(ctypes.c_void_p(self._windows_handle)):
                error = ctypes.get_last_error()
                raise OSError(error, "failed to advance Windows directory change notification", str(self.root))
        self._pending = False

    def close(self) -> None:
        linux_watch, self._linux_watch = self._linux_watch, None
        if linux_watch is not None:
            try:
                linux_watch.close()
            except OSError as exc:
                self._close_error = exc
                raise
        handle, self._windows_handle = self._windows_handle, None
        if handle is not None:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            close = kernel32.FindCloseChangeNotification
            close.argtypes = [ctypes.c_void_p]
            close.restype = ctypes.c_int
            if not close(ctypes.c_void_p(handle)):
                error = ctypes.get_last_error()
                exc = OSError(error, "failed to close Windows directory change notification", str(self.root))
                self._close_error = exc
                raise exc

    def __del__(self) -> None:
        try:
            self.close()
        except Exception as exc:
            if isinstance(exc, OSError):
                self._close_error = exc


__all__ = ["DirectoryChangeSignal"]
