from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
from typing import BinaryIO, Iterator
from uuid import uuid4

from noetrium_platform.foundation.kernel.kernel.retry import retry_until_deadline

if os.name == "nt":
    import ctypes
    from ctypes import wintypes
    import msvcrt


class DurableFileWriteError(RuntimeError):
    """Raised when a durable filesystem publication cannot be completed."""


_WINDOWS_FILE_RETRY_TIMEOUT_SECONDS = 0.5
_WINDOWS_FILE_RETRY_INTERVAL_SECONDS = 0.005
_WINDOWS_TRANSIENT_FILE_ERRORS = frozenset({32, 33})


def _is_transient_windows_file_error(exc: Exception) -> bool:
    return os.name == "nt" and isinstance(exc, OSError) and getattr(exc, "winerror", None) in _WINDOWS_TRANSIENT_FILE_ERRORS


def _windows_file_operation(operation):
    if os.name != "nt":
        return operation()
    return retry_until_deadline(
        operation,
        should_retry=_is_transient_windows_file_error,
        timeout_seconds=_WINDOWS_FILE_RETRY_TIMEOUT_SECONDS,
        interval_seconds=_WINDOWS_FILE_RETRY_INTERVAL_SECONDS,
    )


def flush_file_descriptor(fd: int) -> None:
    if os.name != "nt":
        os.fsync(fd)
        return

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    flush_buffers = kernel32.FlushFileBuffers
    flush_buffers.argtypes = (wintypes.HANDLE,)
    flush_buffers.restype = wintypes.BOOL
    handle = msvcrt.get_osfhandle(fd)
    if not flush_buffers(handle):
        error = ctypes.get_last_error()
        raise OSError(error, "failed to flush file contents")


def _flush_file(path: Path) -> None:
    def flush() -> None:
        with path.open("r+b") as handle:
            handle.flush()
            flush_file_descriptor(handle.fileno())

    _windows_file_operation(flush)


def fsync_directory(path: Path) -> None:
    """Persist directory-entry updates for *path*.

    File fsync alone does not make a rename durable across power loss.  The
    directory containing the replaced entry must also be fsynced.  This helper
    deliberately knows nothing about document formats or domain state.
    """

    if os.name == "nt":
        # Windows does not expose directory handles through os.open.  Open the
        # directory with FILE_FLAG_BACKUP_SEMANTICS and flush the handle through
        # the native API, preserving the post-rename durability step instead of
        # silently dropping it on the development platform.
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        create_file.restype = wintypes.HANDLE
        flush_buffers = kernel32.FlushFileBuffers
        flush_buffers.argtypes = (wintypes.HANDLE,)
        flush_buffers.restype = wintypes.BOOL
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL

        handle = create_file(
            str(path),
            0xC0000000,  # GENERIC_READ | GENERIC_WRITE; required by FlushFileBuffers for directories
            0x00000001 | 0x00000002 | 0x00000004,  # share read/write/delete
            None,
            3,  # OPEN_EXISTING
            0x02000000,  # FILE_FLAG_BACKUP_SEMANTICS
            None,
        )
        invalid = wintypes.HANDLE(-1).value
        if handle == invalid:
            error = ctypes.get_last_error()
            raise OSError(error, f"failed to open directory for durable flush: {path}")
        try:
            if not flush_buffers(handle):
                error = ctypes.get_last_error()
                raise OSError(error, f"failed to flush directory metadata: {path}")
        finally:
            close_handle(handle)
        return

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def durable_create_binary_file(
    path: Path,
    *,
    buffering: int = -1,
) -> Iterator[BinaryIO]:
    """Create one new binary file and make its completed contents durable.

    The caller owns the streamed payload and domain validation. Platform
    durability owns exclusive creation, flush/fsync, parent publication and
    partial-file cleanup on failure.
    """
    if type(buffering) is not int or buffering < -1:
        raise ValueError("durable file buffering must be -1 or non-negative")
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("xb", buffering=buffering)
    primary: BaseException | None = None
    try:
        yield handle
        handle.flush()
        flush_file_descriptor(handle.fileno())
    except BaseException as exc:
        primary = exc
        raise
    finally:
        try:
            handle.close()
        except BaseException as close_exc:
            if primary is None:
                raise
            primary.add_note(
                "durable create close failed: "
                f"{type(close_exc).__name__}"
            )
        if primary is None:
            fsync_directory(parent)
        else:
            try:
                _windows_file_operation(lambda: path.unlink(missing_ok=True))
                fsync_directory(parent)
            except BaseException as cleanup_exc:
                primary.add_note(
                    "durable create cleanup failed: "
                    f"{type(cleanup_exc).__name__}"
                )


def durable_publish_immutable_bytes(
    path: Path,
    payload: bytes,
    *,
    staging_dir: Path | None = None,
) -> None:
    """Durably publish immutable bytes without exposing a partial target.

    Publication is staged in a unique file, fsynced, then linked into the
    canonical pathname with no-replace semantics. A crash before the link can
    leave only a non-canonical staging file; a crash after the link leaves a
    complete canonical inode. Callers may retry and verify an existing target
    after FileExistsError.
    """
    if type(payload) is not bytes:
        raise TypeError("immutable durable payload must be bytes")
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = parent if staging_dir is None else Path(staging_dir)
    staging.mkdir(parents=True, exist_ok=True)
    tmp = staging / f"{path.name}.immutable.{os.getpid()}.{uuid4().hex}"
    primary: BaseException | None = None
    try:
        with tmp.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            flush_file_descriptor(handle.fileno())
        fsync_directory(staging)
        _windows_file_operation(lambda: os.link(tmp, path))
        fsync_directory(parent)
    except FileExistsError as exc:
        primary = exc
        raise
    except BaseException as exc:
        primary = exc
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise DurableFileWriteError(
            f"durable immutable publication failed for {path}"
        ) from exc
    finally:
        try:
            if tmp.exists():
                _windows_file_operation(lambda: tmp.unlink(missing_ok=True))
                fsync_directory(staging)
        except BaseException as cleanup_exc:
            if primary is None:
                raise
            primary.add_note(
                "immutable publication staging cleanup failed: "
                f"{type(cleanup_exc).__name__}"
            )


def durable_truncate_file(path: Path, size: int) -> None:
    """Truncate an existing file and persist the new durable byte boundary."""
    if type(size) is not int or size < 0:
        raise ValueError("durable truncate size must be a non-negative integer")
    try:
        with path.open("r+b") as handle:
            handle.truncate(size)
            handle.flush()
            flush_file_descriptor(handle.fileno())
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise DurableFileWriteError(
            f"durable truncate failed for {path}"
        ) from exc


def atomic_replace_bytes(path: Path, payload: bytes) -> None:
    """Durably publish *payload* at *path* using same-directory atomic replace.

    The protocol is intentionally minimal and domain-agnostic:

        write unique temp -> fsync(temp) -> replace -> fsync(parent)

    A unique temp name avoids concurrent writers corrupting one another's temp
    file.  Higher layers remain responsible for single-writer/CAS semantics and
    document schemas/checksums.
    """

    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp = parent / f".{path.name}.tmp.{os.getpid()}.{uuid4().hex}"
    published = False
    try:
        with tmp.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            flush_file_descriptor(handle.fileno())
        _windows_file_operation(lambda: os.replace(tmp, path))
        published = True
        fsync_directory(parent)
    except BaseException as exc:
        if not published:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise DurableFileWriteError(f"durable atomic publication failed for {path}") from exc


def durable_replace_file(source: Path, target: Path) -> None:
    """Durably replace *target* with an already materialized file *source*.

    This variant is intended for large generated artifacts such as rebuilt
    SQLite databases where re-reading the whole source into memory merely to
    call :func:`atomic_replace_bytes` would be wasteful.  The source file is
    fsynced before rename and the target directory is fsynced afterwards.
    """

    target.parent.mkdir(parents=True, exist_ok=True)
    _flush_file(source)
    try:
        _windows_file_operation(lambda: os.replace(source, target))
        fsync_directory(target.parent)
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise DurableFileWriteError(
            f"durable file replacement failed: {source} -> {target}"
        ) from exc


def durable_replace_directory(source: Path, target: Path) -> None:
    """Durably publish a fully materialized directory through one atomic rename.

    Callers own the directory contents and schema. Platform durability owns the
    publication mechanism: flush the source directory metadata, atomically
    replace the target entry, then flush the parent directory.
    """

    target.parent.mkdir(parents=True, exist_ok=True)
    fsync_directory(source)
    try:
        _windows_file_operation(lambda: os.replace(source, target))
        fsync_directory(target.parent)
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise DurableFileWriteError(
            f"durable directory replacement failed: {source} -> {target}"
        ) from exc


def durable_unlink(path: Path) -> None:
    """Remove *path* and persist the directory-entry deletion."""

    if not path.exists():
        return
    _windows_file_operation(path.unlink)
    fsync_directory(path.parent)


__all__ = [
    "DurableFileWriteError",
    "atomic_replace_bytes",
    "durable_create_binary_file",
    "durable_publish_immutable_bytes",
    "durable_truncate_file",
    "durable_replace_file",
    "durable_replace_directory",
    "durable_unlink",
    "fsync_directory",
    "flush_file_descriptor",
]
