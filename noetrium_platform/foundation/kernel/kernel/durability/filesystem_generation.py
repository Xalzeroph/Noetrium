from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import shutil
import stat as stat_module

from .durable_file import fsync_directory


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
    "FilesystemCarrierKind",
    "capture_filesystem_carrier_generation",
    "purge_directory_contents",
    "remove_empty_directory_carrier",
    "rename_directory_carrier",
]
