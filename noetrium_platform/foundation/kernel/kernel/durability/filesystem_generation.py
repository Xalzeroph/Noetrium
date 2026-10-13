from __future__ import annotations

from dataclasses import dataclass
import ctypes
import os
import sys
from enum import StrEnum
from pathlib import Path
import shutil
import stat as stat_module

from .durable_file import fsync_directory


def filesystem_birth_time_ns(path: Path) -> int | None:
    """Return stable filesystem object birth time in nanoseconds when available.

    Birth time is invariant across same-filesystem rename and changes when an
    inode number is recycled for a new object. It therefore closes the inode
    reuse hole that device+inode alone cannot distinguish.
    """
    target = Path(path)
    identity = target.stat(follow_symlinks=False)
    direct_ns = getattr(identity, "st_birthtime_ns", None)
    if type(direct_ns) is int and direct_ns >= 0:
        return direct_ns
    direct = getattr(identity, "st_birthtime", None)
    if isinstance(direct, (int, float)) and direct >= 0:
        return int(direct * 1_000_000_000)
    if not sys.platform.startswith("linux"):
        return None

    class _StatxTimestamp(ctypes.Structure):
        _fields_ = [
            ("tv_sec", ctypes.c_longlong),
            ("tv_nsec", ctypes.c_uint),
            ("__reserved", ctypes.c_int),
        ]

    class _Statx(ctypes.Structure):
        _fields_ = [
            ("stx_mask", ctypes.c_uint),
            ("stx_blksize", ctypes.c_uint),
            ("stx_attributes", ctypes.c_ulonglong),
            ("stx_nlink", ctypes.c_uint),
            ("stx_uid", ctypes.c_uint),
            ("stx_gid", ctypes.c_uint),
            ("stx_mode", ctypes.c_ushort),
            ("__spare0", ctypes.c_ushort),
            ("stx_ino", ctypes.c_ulonglong),
            ("stx_size", ctypes.c_ulonglong),
            ("stx_blocks", ctypes.c_ulonglong),
            ("stx_attributes_mask", ctypes.c_ulonglong),
            ("stx_atime", _StatxTimestamp),
            ("stx_btime", _StatxTimestamp),
            ("stx_ctime", _StatxTimestamp),
            ("stx_mtime", _StatxTimestamp),
            ("stx_rdev_major", ctypes.c_uint),
            ("stx_rdev_minor", ctypes.c_uint),
            ("stx_dev_major", ctypes.c_uint),
            ("stx_dev_minor", ctypes.c_uint),
            ("stx_mnt_id", ctypes.c_ulonglong),
            ("stx_dio_mem_align", ctypes.c_uint),
            ("stx_dio_offset_align", ctypes.c_uint),
            ("__spare3", ctypes.c_ulonglong * 12),
        ]

    libc = ctypes.CDLL(None, use_errno=True)
    statx = getattr(libc, "statx", None)
    if statx is None:
        return None
    statx.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.POINTER(_Statx),
    ]
    statx.restype = ctypes.c_int
    row = _Statx()
    at_fdcwd = -100
    at_symlink_nofollow = 0x100
    statx_btime = 0x800
    rc = statx(
        at_fdcwd,
        os.fsencode(target),
        at_symlink_nofollow,
        statx_btime,
        ctypes.byref(row),
    )
    if rc != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(target))
    if not (row.stx_mask & statx_btime):
        return None
    return int(row.stx_btime.tv_sec) * 1_000_000_000 + int(row.stx_btime.tv_nsec)


class FilesystemCarrierKind(StrEnum):
    REGULAR_FILE = "regular-file"
    DIRECTORY = "directory"


@dataclass(frozen=True, slots=True)
class FilesystemCarrierGeneration:
    """Exact physical filesystem generation for one durable carrier path.

    Device and inode identify the same filesystem object across a
    same-filesystem rename. change_time_ns fences later mutation or inode
    reuse once a carrier has reached its stable post-rename location.
    """

    kind: FilesystemCarrierKind
    device: int
    inode: int
    change_time_ns: int

    def __post_init__(self) -> None:
        if type(self.kind) is not FilesystemCarrierKind:
            raise TypeError("filesystem carrier generation kind must be typed")
        for name, value in (
            ("device", self.device),
            ("inode", self.inode),
            ("change_time_ns", self.change_time_ns),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(
                    f"filesystem carrier generation {name} must be a non-negative integer"
                )

    def same_object(self, other: object) -> bool:
        return (
            type(other) is FilesystemCarrierGeneration
            and self.kind is other.kind
            and self.device == other.device
            and self.inode == other.inode
        )

    def same_generation(self, other: object) -> bool:
        return type(other) is FilesystemCarrierGeneration and self == other

    def to_data(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "device": self.device,
            "inode": self.inode,
            "change_time_ns": self.change_time_ns,
        }

    @classmethod
    def from_data(cls, value: object) -> "FilesystemCarrierGeneration":
        if type(value) is not dict or set(value) != {
            "kind",
            "device",
            "inode",
            "change_time_ns",
        }:
            raise ValueError("filesystem carrier generation payload shape is invalid")
        try:
            kind = FilesystemCarrierKind(value["kind"])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "filesystem carrier generation kind is invalid"
            ) from exc
        return cls(
            kind=kind,
            device=value["device"],
            inode=value["inode"],
            change_time_ns=value["change_time_ns"],
        )


def capture_filesystem_carrier_generation(
    path: Path,
    *,
    expected_kind: FilesystemCarrierKind,
) -> FilesystemCarrierGeneration:
    if type(expected_kind) is not FilesystemCarrierKind:
        raise TypeError("expected filesystem carrier kind must be typed")
    identity = path.stat(follow_symlinks=False)
    if stat_module.S_ISREG(identity.st_mode):
        kind = FilesystemCarrierKind.REGULAR_FILE
    elif stat_module.S_ISDIR(identity.st_mode):
        kind = FilesystemCarrierKind.DIRECTORY
    else:
        raise RuntimeError(f"unsupported durable filesystem carrier: {path}")
    if kind is not expected_kind:
        raise RuntimeError(
            "durable filesystem carrier kind mismatch: "
            f"expected={expected_kind.value} actual={kind.value} path={path}"
        )
    return FilesystemCarrierGeneration(
        kind=kind,
        device=int(identity.st_dev),
        inode=int(identity.st_ino),
        change_time_ns=int(identity.st_ctime_ns),
    )


def rename_directory_carrier(
    source: Path,
    destination: Path,
    *,
    expected_generation: FilesystemCarrierGeneration,
) -> FilesystemCarrierGeneration:
    """Rename one exact directory object and durably publish the new name."""

    if (
        type(expected_generation) is not FilesystemCarrierGeneration
        or expected_generation.kind is not FilesystemCarrierKind.DIRECTORY
    ):
        raise TypeError(
            "directory rename requires a typed directory carrier generation"
        )
    current = capture_filesystem_carrier_generation(
        source,
        expected_kind=FilesystemCarrierKind.DIRECTORY,
    )
    if not expected_generation.same_generation(current):
        raise RuntimeError(
            "directory carrier generation changed before rename"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise RuntimeError(
            f"directory carrier destination already exists: {destination}"
        )
    try:
        source.rename(destination)
    except OSError:
        # rename(2) may have committed before an I/O error reached the caller.
        if source.exists() or not destination.exists():
            raise
    moved = capture_filesystem_carrier_generation(
        destination,
        expected_kind=FilesystemCarrierKind.DIRECTORY,
    )
    if not expected_generation.same_object(moved):
        raise RuntimeError(
            "directory carrier object changed across rename"
        )
    fsync_directory(source.parent)
    if destination.parent != source.parent:
        fsync_directory(destination.parent)
    return moved


def purge_directory_contents(
    root: Path,
    *,
    expected_generation: FilesystemCarrierGeneration,
) -> FilesystemCarrierGeneration:
    """Remove descendants while deliberately preserving the owned root inode.

    Keeping the root directory present makes recursive deletion crash-retryable:
    a same-path replacement cannot occupy the name until the original root has
    been reduced to an empty, separately committed generation.
    """

    if (
        type(expected_generation) is not FilesystemCarrierGeneration
        or expected_generation.kind is not FilesystemCarrierKind.DIRECTORY
    ):
        raise TypeError(
            "directory purge requires a typed directory carrier generation"
        )
    current = capture_filesystem_carrier_generation(
        root,
        expected_kind=FilesystemCarrierKind.DIRECTORY,
    )
    if not expected_generation.same_object(current):
        raise RuntimeError(
            "directory carrier object changed during recursive purge"
        )
    for child in tuple(root.iterdir()):
        if child.is_symlink() or not child.is_dir():
            child.unlink()
        else:
            shutil.rmtree(child)
    fsync_directory(root)
    emptied = capture_filesystem_carrier_generation(
        root,
        expected_kind=FilesystemCarrierKind.DIRECTORY,
    )
    if not expected_generation.same_object(emptied):
        raise RuntimeError(
            "directory carrier object changed while clearing descendants"
        )
    if any(root.iterdir()):
        raise RuntimeError(
            "directory carrier is not empty after descendant purge"
        )
    return emptied


def remove_empty_directory_carrier(
    root: Path,
    *,
    expected_generation: FilesystemCarrierGeneration,
) -> bool:
    """Remove one exact empty directory generation with durable parent sync."""

    if (
        type(expected_generation) is not FilesystemCarrierGeneration
        or expected_generation.kind is not FilesystemCarrierKind.DIRECTORY
    ):
        raise TypeError(
            "empty directory removal requires a typed directory carrier generation"
        )
    if not root.exists():
        return False
    current = capture_filesystem_carrier_generation(
        root,
        expected_kind=FilesystemCarrierKind.DIRECTORY,
    )
    if not expected_generation.same_generation(current):
        raise RuntimeError(
            "empty directory carrier generation changed before removal"
        )
    if any(root.iterdir()):
        raise RuntimeError(
            "empty directory carrier gained descendants before removal"
        )
    root.rmdir()
    fsync_directory(root.parent)
    return True


__all__ = [
    "FilesystemCarrierGeneration",
    "filesystem_birth_time_ns",
    "FilesystemCarrierKind",
    "capture_filesystem_carrier_generation",
    "purge_directory_contents",
    "remove_empty_directory_carrier",
    "rename_directory_carrier",
]
