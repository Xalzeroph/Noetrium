from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import stat as stat_module


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


__all__ = [
    "FilesystemCarrierGeneration",
    "FilesystemCarrierKind",
    "capture_filesystem_carrier_generation",
]
