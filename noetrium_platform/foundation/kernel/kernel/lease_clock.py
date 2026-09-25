"""Boot-aware lease clock shared by all ownership authorities.

Elapsed time inside one boot domain is the only expiration authority. Wall time
is captured only to establish a human-readable logical epoch and never decides
whether a lease is live. Host or boot identity changes are explicit ownership
events rather than silent clock drift.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from hashlib import sha256
import math
import os
from pathlib import Path
import sys
import time
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class LeaseClockReading:
    host_identity_digest: str
    boot_identity_digest: str
    elapsed_seconds: float
    wall_epoch_seconds: float

    def __post_init__(self) -> None:
        for name, value in (
            ("host_identity_digest", self.host_identity_digest),
            ("boot_identity_digest", self.boot_identity_digest),
        ):
            if (
                type(value) is not str
                or len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise ValueError(f"lease clock {name} must be lowercase sha256")
        if type(self.elapsed_seconds) not in (int, float):
            raise TypeError("lease clock elapsed_seconds must be int or float")
        if (
            not math.isfinite(float(self.elapsed_seconds))
            or self.elapsed_seconds < 0
        ):
            raise ValueError(
                "lease clock elapsed_seconds must be finite and non-negative"
            )
        if (
            not math.isfinite(float(self.wall_epoch_seconds))
            or self.wall_epoch_seconds <= 0
        ):
            raise ValueError(
                "lease clock wall_epoch_seconds must be finite and positive"
            )


@runtime_checkable
class LeaseClockPort(Protocol):
    def read(self) -> LeaseClockReading: ...


class LeaseClockUnavailable(RuntimeError):
    """The host cannot provide a stable host plus boot clock domain."""


def _digest(kind: str, *parts: str) -> str:
    payload = "\0".join((kind, *parts)).encode("utf-8")
    return sha256(payload).hexdigest()


def _read_text(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _linux_reading() -> LeaseClockReading:
    explicit_host = os.environ.get("NOETRIUM_HOST_IDENTITY", "").strip()
    host_parts: list[str] = []
    if explicit_host:
        host_parts.append("explicit:" + explicit_host)
    for label, path in (
        ("dmi", Path("/sys/class/dmi/id/product_uuid")),
        ("machine", Path("/etc/machine-id")),
    ):
        value = _read_text(path)
        if value:
            host_parts.append(f"{label}:{value}")
    if not host_parts:
        raise LeaseClockUnavailable(
            "Linux lease clock requires a stable host identity"
        )

    boot_id = _read_text(Path("/proc/sys/kernel/random/boot_id"))
    if boot_id is None:
        raise LeaseClockUnavailable(
            "Linux lease clock requires /proc boot identity"
        )
    clock_id = getattr(time, "CLOCK_BOOTTIME", None)
    if clock_id is None:
        raise LeaseClockUnavailable(
            "Linux lease clock requires suspend-aware CLOCK_BOOTTIME"
        )
    elapsed = time.clock_gettime(clock_id)
    return LeaseClockReading(
        _digest("noetrium-lease-host-v1", *sorted(host_parts)),
        _digest("noetrium-lease-boot-v1", boot_id),
        elapsed,
        time.time(),
    )


class _Guid(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _SystemBootEnvironmentInformation(ctypes.Structure):
    _fields_ = [
        ("BootIdentifier", _Guid),
        ("FirmwareType", wintypes.DWORD),
        ("BootFlags", ctypes.c_ulonglong),
    ]


def _windows_reading() -> LeaseClockReading:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
        ) as key:
            machine_guid = str(
                winreg.QueryValueEx(key, "MachineGuid")[0]
            ).strip()
    except (OSError, ImportError, AttributeError) as exc:
        raise LeaseClockUnavailable(
            "Windows lease clock requires MachineGuid"
        ) from exc
    if not machine_guid:
        raise LeaseClockUnavailable("Windows MachineGuid is empty")

    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    query = ntdll.NtQuerySystemInformation
    query.argtypes = [
        wintypes.ULONG,
        ctypes.c_void_p,
        wintypes.ULONG,
        ctypes.POINTER(wintypes.ULONG),
    ]
    query.restype = ctypes.c_long
    info = _SystemBootEnvironmentInformation()
    returned = wintypes.ULONG()
    status = int(
        query(
            90,
            ctypes.byref(info),
            ctypes.sizeof(info),
            ctypes.byref(returned),
        )
    )
    if status < 0:
        raise LeaseClockUnavailable(
            f"NtQuerySystemInformation boot identity failed: ntstatus={status:#x}"
        )
    boot_bytes = ctypes.string_at(
        ctypes.byref(info.BootIdentifier),
        ctypes.sizeof(info.BootIdentifier),
    )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetTickCount64.restype = ctypes.c_ulonglong
    elapsed = float(kernel32.GetTickCount64()) / 1000.0
    return LeaseClockReading(
        _digest("noetrium-lease-host-v1", "machine-guid:" + machine_guid),
        sha256(b"noetrium-lease-boot-v1\0" + boot_bytes).hexdigest(),
        elapsed,
        time.time(),
    )


class LocalLeaseClock(LeaseClockPort):
    """OS-backed lease clock with stable host and per-boot identity."""

    def read(self) -> LeaseClockReading:
        if sys.platform.startswith("linux"):
            return _linux_reading()
        if sys.platform == "win32":
            return _windows_reading()
        raise LeaseClockUnavailable(
            f"unsupported durable lease clock platform: {sys.platform}"
        )


class ManualLeaseClock(LeaseClockPort):
    """Deterministic boot-aware clock for lifecycle/crash-window tests."""

    def __init__(
        self,
        *,
        elapsed_seconds: float = 1.0,
        wall_epoch_seconds: float = 1_000_000.0,
        host_seed: str = "host",
        boot_seed: str = "boot-1",
    ) -> None:
        if type(host_seed) is not str or type(boot_seed) is not str:
            raise TypeError("manual lease clock seeds must be str")
        if not host_seed.strip() or not boot_seed.strip():
            raise ValueError("manual lease clock seeds must be non-empty")
        if type(elapsed_seconds) not in (int, float) or type(wall_epoch_seconds) not in (int, float):
            raise TypeError("manual lease clock times must be int or float")
        elapsed = float(elapsed_seconds)
        wall = float(wall_epoch_seconds)
        if not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("manual lease elapsed time must be finite and non-negative")
        if not math.isfinite(wall) or wall <= 0:
            raise ValueError("manual lease wall time must be finite and positive")
        self._host_seed = host_seed
        self._boot_seed = boot_seed
        self._elapsed = elapsed
        self._wall = wall

    def read(self) -> LeaseClockReading:
        return LeaseClockReading(
            _digest("manual-lease-host-v1", self._host_seed),
            _digest("manual-lease-boot-v1", self._boot_seed),
            self._elapsed,
            self._wall,
        )

    def advance(
        self,
        seconds: float,
        *,
        wall_seconds: float | None = None,
    ) -> None:
        seconds = float(seconds)
        if seconds < 0:
            raise ValueError("manual lease elapsed time cannot move backwards")
        self._elapsed += seconds
        self._wall += (
            seconds if wall_seconds is None else float(wall_seconds)
        )

    def jump_wall(self, seconds: float) -> None:
        self._wall += float(seconds)

    def reboot(
        self,
        *,
        boot_seed: str,
        elapsed_seconds: float = 0.0,
    ) -> None:
        if not boot_seed.strip() or boot_seed == self._boot_seed:
            raise ValueError(
                "manual lease reboot requires a new boot identity"
            )
        self._boot_seed = boot_seed
        self._elapsed = float(elapsed_seconds)

    def move_host(self, *, host_seed: str) -> None:
        if not host_seed.strip() or host_seed == self._host_seed:
            raise ValueError(
                "manual lease host move requires a new host identity"
            )
        self._host_seed = host_seed


__all__ = [
    "LeaseClockPort",
    "LeaseClockReading",
    "LeaseClockUnavailable",
    "LocalLeaseClock",
    "ManualLeaseClock",
]
