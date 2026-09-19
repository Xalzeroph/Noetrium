from __future__ import annotations

import hashlib
import os
from pathlib import Path
import threading
from types import TracebackType

from noetrium_platform.foundation.kernel.kernel.logical_path import logical_absolute_path

if os.name == "nt":
    import ctypes
    from ctypes import wintypes
else:
    import fcntl


class InterprocessLockUnavailable(RuntimeError):
    pass


class InterprocessLockBusy(RuntimeError):
    pass


_LOCAL_MUTEX_NAMES: set[str] = set()
_LOCAL_MUTEX_GUARD = threading.Lock()


class InterprocessFileLock:
    """Cross-platform lock for cross-process read/modify/write guards.

    The lock file is intentionally persistent.  Unlinking a lock file while
    another process holds the inode can create two independent lock domains.
    Process exit releases the kernel lock automatically.
    """

    def __init__(self, path: Path, *, blocking: bool = True) -> None:
        self.path = path
        self.blocking = blocking
        self._fd: int | None = None
        self._handle: int | None = None
        self._mutex_name: str | None = None

    @staticmethod
    def _canonical_windows_path_identity(path: Path) -> str:
        """Collapse equivalent Win32 and extended-length path namespaces."""

        resolved = str(logical_absolute_path(path))
        extended_unc = "\\\\?\\UNC\\"
        extended = "\\\\?\\"
        if resolved.upper().startswith(extended_unc.upper()):
            resolved = "\\\\" + resolved[len(extended_unc):]
        elif resolved.startswith(extended):
            tail = resolved[len(extended):]
            if len(tail) >= 3 and tail[0].isalpha() and tail[1] == ":" and tail[2] in "\\/":
                resolved = tail
        return resolved.replace("/", "\\").casefold()

    def _windows_mutex_name(self) -> str:
        identity = self._canonical_windows_path_identity(self.path).encode("utf-8", "surrogatepass")
        return "Local\\NoetriumLock-" + hashlib.sha256(identity).hexdigest()

    def __enter__(self) -> "InterprocessFileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            # The marker is intentionally not the kernel lock object. A named
            # mutex keeps one lock domain even if a test/operator removes the
            # marker during a still-live owner process, while allowing Windows
            # to remove temporary directories without waiting for an open file
            # handle. The mutex name is a digest of the canonical lock path.
            self.path.touch(exist_ok=True)
            mutex_name = self._windows_mutex_name()
            with _LOCAL_MUTEX_GUARD:
                if mutex_name in _LOCAL_MUTEX_NAMES:
                    raise InterprocessLockBusy(f"interprocess lock busy: {self.path}")
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            create_mutex = kernel32.CreateMutexW
            create_mutex.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
            create_mutex.restype = wintypes.HANDLE
            wait_for_single_object = kernel32.WaitForSingleObject
            wait_for_single_object.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            wait_for_single_object.restype = wintypes.DWORD
            handle = create_mutex(None, False, mutex_name)
            invalid = wintypes.HANDLE(-1).value
            if not handle or handle == invalid:
                error = ctypes.get_last_error()
                raise InterprocessLockUnavailable(
                    f"interprocess lock failed: {self.path} ({error})"
                )
            result = wait_for_single_object(handle, 0 if not self.blocking else 0xFFFFFFFF)
            if result == 0x00000102:  # WAIT_TIMEOUT
                kernel32.CloseHandle(handle)
                raise InterprocessLockBusy(f"interprocess lock busy: {self.path}")
            if result not in {0x00000000, 0x00000080}:  # WAIT_OBJECT_0/WAIT_ABANDONED
                error = ctypes.get_last_error()
                kernel32.CloseHandle(handle)
                raise InterprocessLockUnavailable(
                    f"interprocess lock failed: {self.path} ({error})"
                )
            self._handle = int(handle)
            self._mutex_name = mutex_name
            with _LOCAL_MUTEX_GUARD:
                _LOCAL_MUTEX_NAMES.add(mutex_name)
            return self

        open_flags = os.O_RDWR | os.O_CREAT
        fd = os.open(self.path, open_flags, 0o600)
        try:
            lock_flags = fcntl.LOCK_EX if self.blocking else (fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, lock_flags)
        except (BlockingIOError, OSError) as exc:
            busy = (
                isinstance(exc, BlockingIOError)
                or getattr(exc, "winerror", None) in {33, 36}
            )
            os.close(fd)
            if busy:
                raise InterprocessLockBusy(f"interprocess lock busy: {self.path}") from exc
            raise InterprocessLockUnavailable(f"interprocess lock failed: {self.path}") from exc
        except BaseException:
            os.close(fd)
            raise
        self._fd = fd
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        del exc_type, exc, tb
        fd = self._fd
        self._fd = None
        if fd is None:
            handle = self._handle
            self._handle = None
            if handle is None:
                return
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            release_mutex = kernel32.ReleaseMutex
            release_mutex.argtypes = (wintypes.HANDLE,)
            release_mutex.restype = wintypes.BOOL
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = (wintypes.HANDLE,)
            close_handle.restype = wintypes.BOOL
            try:
                if not release_mutex(handle):
                    error = ctypes.get_last_error()
                    raise OSError(error, f"failed to release interprocess mutex: {self.path}")
            finally:
                if self._mutex_name is not None:
                    with _LOCAL_MUTEX_GUARD:
                        _LOCAL_MUTEX_NAMES.discard(self._mutex_name)
                    self._mutex_name = None
                close_handle(handle)
            return
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


__all__ = ["InterprocessFileLock", "InterprocessLockBusy", "InterprocessLockUnavailable"]
