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


def durable_publish_immutable_bytes_many(
    items: tuple[tuple[Path, bytes], ...],
    *,
    staging_dir: Path | None = None,
) -> None:
    """Durably publish immutable files under one batched directory barrier."""
    if type(items) is not tuple:
        raise TypeError("immutable durable batch must be tuple")
    if not items:
        return

    normalized: list[tuple[Path, bytes]] = []
    targets: set[Path] = set()
    for raw_path, payload in items:
        path = Path(raw_path)
        if type(payload) is not bytes:
            raise TypeError("immutable durable payload must be bytes")
        if path in targets:
            raise ValueError("immutable durable batch contains duplicate target")
        targets.add(path)
        normalized.append((path, payload))

    staging = None if staging_dir is None else Path(staging_dir)
    if staging is not None:
        staging.mkdir(parents=True, exist_ok=True)

    staged: list[tuple[Path, Path]] = []
    target_parents: set[Path] = set()
    staging_parents: set[Path] = set()
    primary: BaseException | None = None
    try:
        for path, payload in normalized:
            parent = path.parent
            parent.mkdir(parents=True, exist_ok=True)
            stage_parent = parent if staging is None else staging
            stage_parent.mkdir(parents=True, exist_ok=True)
            tmp = stage_parent / (
                f"{path.name}.immutable.{os.getpid()}.{uuid4().hex}"
            )
            with tmp.open("xb") as handle:
                handle.write(payload)
                handle.flush()
            staged.append((tmp, path))
            staging_parents.add(stage_parent)

        # Queue all writes before explicit file durability barriers so the
        # filesystem can group dirty-data and journal work.
        for tmp, _path in staged:
            _flush_file(tmp)

        for tmp, path in staged:
            _windows_file_operation(
                lambda tmp=tmp, path=path: os.link(tmp, path)
            )
            target_parents.add(path.parent)

        for parent in sorted(target_parents, key=lambda item: item.as_posix()):
            fsync_directory(parent)
    except FileExistsError as exc:
        primary = exc
        raise
    except BaseException as exc:
        primary = exc
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise DurableFileWriteError(
            "durable immutable batch publication failed"
        ) from exc
    finally:
        cleanup_error: BaseException | None = None
        touched_staging: set[Path] = set()
        for tmp, _path in staged:
            try:
                if tmp.exists():
                    _windows_file_operation(
                        lambda tmp=tmp: tmp.unlink(missing_ok=True)
                    )
                    touched_staging.add(tmp.parent)
            except BaseException as exc:
                if cleanup_error is None:
                    cleanup_error = exc
        # Once every target parent has been fsynced, the immutable authority is
        # durable. A staging unlink is only garbage collection: if power loss
        # resurrects an old staging directory entry, the next publication's
        # existing _cleanup_staging() pass removes it. Do not add a second
        # directory durability barrier to every successful immutable publish.
        # On failed publication we still persist cleanup so a failed mutation
        # converges eagerly instead of leaving ambiguous residue.
        if primary is not None:
            for parent in sorted(
                touched_staging,
                key=lambda item: item.as_posix(),
            ):
                try:
                    fsync_directory(parent)
                except BaseException as exc:
                    if cleanup_error is None:
                        cleanup_error = exc
        if cleanup_error is not None:
            if primary is None:
                raise cleanup_error
            primary.add_note(
                "immutable batch staging cleanup failed: "
                f"{type(cleanup_error).__name__}"
            )


def durable_publish_immutable_bytes(
    path: Path,
    payload: bytes,
    *,
    staging_dir: Path | None = None,
) -> None:
    durable_publish_immutable_bytes_many(
        ((path, payload),),
        staging_dir=staging_dir,
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


def atomic_replace_bytes_many(
    items: tuple[tuple[Path, bytes], ...],
) -> None:
    """Durably replace one or many files through one publication mechanism."""
    if type(items) is not tuple:
        raise TypeError("atomic replace batch must be tuple")
    if not items:
        return

    normalized: list[tuple[Path, bytes]] = []
    targets: set[Path] = set()
    for raw_path, payload in items:
        path = Path(raw_path)
        if type(payload) is not bytes:
            raise TypeError("atomic replace payload must be bytes")
        if path in targets:
            raise ValueError("atomic replace batch contains duplicate target")
        targets.add(path)
        normalized.append((path, payload))

    staged: list[tuple[Path, Path]] = []
    parents: set[Path] = set()
    primary: BaseException | None = None
    try:
        for path, payload in normalized:
            parent = path.parent
            parent.mkdir(parents=True, exist_ok=True)
            tmp = parent / f".{path.name}.tmp.{os.getpid()}.{uuid4().hex}"
            with tmp.open("xb") as handle:
                handle.write(payload)
                handle.flush()
            staged.append((tmp, path))
            parents.add(parent)

        for tmp, _path in staged:
            _flush_file(tmp)

        for tmp, path in staged:
            _windows_file_operation(
                lambda tmp=tmp, path=path: os.replace(tmp, path)
            )

        for parent in sorted(parents, key=lambda item: item.as_posix()):
            fsync_directory(parent)
    except BaseException as exc:
        primary = exc
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise DurableFileWriteError(
            "durable atomic batch publication failed"
        ) from exc
    finally:
        cleanup_error: BaseException | None = None
        cleanup_parents: set[Path] = set()
        for tmp, _path in staged:
            try:
                if tmp.exists():
                    tmp.unlink(missing_ok=True)
                    cleanup_parents.add(tmp.parent)
            except OSError as exc:
                if cleanup_error is None:
                    cleanup_error = exc
        for parent in sorted(cleanup_parents, key=lambda item: item.as_posix()):
            try:
                fsync_directory(parent)
            except BaseException as exc:
                if cleanup_error is None:
                    cleanup_error = exc
        if cleanup_error is not None:
            if primary is None:
                raise cleanup_error
            primary.add_note(
                "atomic batch staging cleanup failed: "
                f"{type(cleanup_error).__name__}"
            )


def atomic_replace_bytes(path: Path, payload: bytes) -> None:
    atomic_replace_bytes_many(((path, payload),))


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
    "atomic_replace_bytes_many",
    "durable_create_binary_file",
    "durable_publish_immutable_bytes",
    "durable_publish_immutable_bytes_many",
    "durable_truncate_file",
    "durable_replace_file",
    "durable_replace_directory",
    "durable_unlink",
    "fsync_directory",
    "flush_file_descriptor",
]
