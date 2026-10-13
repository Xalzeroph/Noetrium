"""Machine authority lease with boot-aware monotonic epoch fencing.

Machine authority is distinct from resource and recovery ownership, but it uses
exactly the same host/boot clock contract. Mutable wall time is never lease
expiration authority.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
from threading import RLock
from typing import Protocol, runtime_checkable

from .canonical import canonical_bytes, canonical_digest, strict_json_loads
from .durability.durable_file import atomic_replace_bytes
from .durability.file_lock import InterprocessFileLock
from .lease_clock import LeaseClockPort, LeaseClockReading, LocalLeaseClock


class MachineAuthorityError(RuntimeError):
    """Base error for machine authority violations."""


class MachineLeaseBusy(MachineAuthorityError):
    """Another live owner currently has the machine authority."""


class MachineLeaseLost(MachineAuthorityError):
    """The caller's lease is missing, expired, rebooted, or fenced."""


class MachineLeaseClockConflict(MachineAuthorityError):
    """Machine authority clock identity is invalid or belongs to another host."""


@dataclass(frozen=True, slots=True)
class MachineLease:
    machine_id: str
    owner_id: str
    epoch: int
    acquired_at: float
    expires_at: float
    host_identity_digest: str
    boot_identity_digest: str
    released: bool = False
    lease_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.machine_id.strip() or not self.owner_id.strip():
            raise ValueError("machine lease identity fields are required")
        if type(self.epoch) is not int or self.epoch < 1:
            raise ValueError("machine lease epoch must be positive")
        for name, value in (
            ("acquired_at", self.acquired_at),
            ("expires_at", self.expires_at),
        ):
            if not math.isfinite(float(value)):
                raise ValueError(f"machine lease {name} must be finite")
        if self.expires_at <= self.acquired_at:
            raise ValueError("machine lease expiry must be after acquisition")
        for name, value in (
            ("host_identity_digest", self.host_identity_digest),
            ("boot_identity_digest", self.boot_identity_digest),
        ):
            if (
                type(value) is not str
                or len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise ValueError(f"machine lease {name} must be lowercase sha256")
        if type(self.released) is not bool:
            raise TypeError("machine lease released must be bool")
        object.__setattr__(
            self,
            "lease_digest",
            canonical_digest({
                "machine_id": self.machine_id,
                "owner_id": self.owner_id,
                "epoch": self.epoch,
                "acquired_at": self.acquired_at,
                "expires_at": self.expires_at,
                "host_identity_digest": self.host_identity_digest,
                "boot_identity_digest": self.boot_identity_digest,
                "released": self.released,
            }),
        )

    def belongs_to(self, reading: LeaseClockReading) -> bool:
        return (
            self.host_identity_digest == reading.host_identity_digest
            and self.boot_identity_digest == reading.boot_identity_digest
        )

    def is_live(self, now: float, reading: LeaseClockReading) -> bool:
        return (
            not self.released
            and self.belongs_to(reading)
            and self.expires_at > float(now)
        )


@runtime_checkable
class MachineAuthorityPort(Protocol):
    def acquire(
        self,
        machine_id: str,
        owner_id: str,
        *,
        ttl_seconds: float = 30.0,
    ) -> MachineLease: ...
    def renew(
        self,
        lease: MachineLease,
        *,
        ttl_seconds: float = 30.0,
    ) -> MachineLease: ...
    def assert_held(self, lease: MachineLease) -> MachineLease: ...
    def release(self, lease: MachineLease) -> None: ...


@dataclass(frozen=True, slots=True)
class _ClockAnchor:
    host_identity_digest: str
    boot_identity_digest: str
    elapsed_seconds: float
    logical_epoch_seconds: float

    @classmethod
    def from_reading(cls, reading: LeaseClockReading) -> "_ClockAnchor":
        return cls(
            reading.host_identity_digest,
            reading.boot_identity_digest,
            float(reading.elapsed_seconds),
            float(reading.wall_epoch_seconds),
        )

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
                raise ValueError(f"machine clock anchor {name} is invalid")
        if (
            not math.isfinite(self.elapsed_seconds)
            or self.elapsed_seconds < 0
            or not math.isfinite(self.logical_epoch_seconds)
            or self.logical_epoch_seconds <= 0
        ):
            raise ValueError("machine clock anchor time values are invalid")


def _ttl(ttl_seconds: float) -> float:
    value = float(ttl_seconds)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("machine authority ttl_seconds must be finite and positive")
    return value


class InMemoryMachineAuthority:
    """Boot-aware deterministic authority for embedded execution and tests."""

    def __init__(self, *, clock: LeaseClockPort | None = None) -> None:
        self._clock = LocalLeaseClock() if clock is None else clock
        if not isinstance(self._clock, LeaseClockPort):
            raise TypeError("machine authority clock must implement LeaseClockPort")
        self._leases: dict[str, MachineLease] = {}
        self._clock_anchor: _ClockAnchor | None = None
        self._lock = RLock()

    def _authority_now_unlocked(
        self,
    ) -> tuple[float, LeaseClockReading]:
        reading = self._clock.read()
        anchor = self._clock_anchor
        if anchor is None:
            self._clock_anchor = _ClockAnchor.from_reading(reading)
            return float(reading.wall_epoch_seconds), reading
        if anchor.host_identity_digest != reading.host_identity_digest:
            raise MachineLeaseClockConflict(
                "machine authority belongs to a different host clock domain"
            )
        if anchor.boot_identity_digest != reading.boot_identity_digest:
            self._clock_anchor = _ClockAnchor.from_reading(reading)
            return float(reading.wall_epoch_seconds), reading
        if reading.elapsed_seconds < anchor.elapsed_seconds:
            raise MachineLeaseClockConflict(
                "same-boot machine lease clock moved backwards"
            )
        return (
            anchor.logical_epoch_seconds
            + (reading.elapsed_seconds - anchor.elapsed_seconds),
            reading,
        )

    def acquire(
        self,
        machine_id: str,
        owner_id: str,
        *,
        ttl_seconds: float = 30.0,
    ) -> MachineLease:
        if not machine_id.strip() or not owner_id.strip():
            raise ValueError("machine authority machine_id and owner_id are required")
        ttl = _ttl(ttl_seconds)
        with self._lock:
            now, reading = self._authority_now_unlocked()
            current = self._leases.get(machine_id)
            if current is not None and current.is_live(now, reading):
                if current.owner_id != owner_id:
                    raise MachineLeaseBusy(
                        f"machine authority held by {current.owner_id}"
                    )
                return current
            epoch = 1 if current is None else current.epoch + 1
            lease = MachineLease(
                machine_id,
                owner_id,
                epoch,
                now,
                now + ttl,
                reading.host_identity_digest,
                reading.boot_identity_digest,
            )
            self._leases[machine_id] = lease
            return lease

    def renew(
        self,
        lease: MachineLease,
        *,
        ttl_seconds: float = 30.0,
    ) -> MachineLease:
        ttl = _ttl(ttl_seconds)
        with self._lock:
            now, reading = self._authority_now_unlocked()
            current = self._leases.get(lease.machine_id)
            if (
                current != lease
                or not current.is_live(now, reading)
            ):
                raise MachineLeaseLost("machine authority cannot be renewed")
            renewed = MachineLease(
                lease.machine_id,
                lease.owner_id,
                lease.epoch,
                lease.acquired_at,
                now + ttl,
                reading.host_identity_digest,
                reading.boot_identity_digest,
            )
            self._leases[lease.machine_id] = renewed
            return renewed

    def assert_held(self, lease: MachineLease) -> MachineLease:
        with self._lock:
            now, reading = self._authority_now_unlocked()
            current = self._leases.get(lease.machine_id)
            if (
                current != lease
                or not current.is_live(now, reading)
            ):
                raise MachineLeaseLost("machine authority is not held")
            return current

    def release(self, lease: MachineLease) -> None:
        with self._lock:
            now, reading = self._authority_now_unlocked()
            current = self._leases.get(lease.machine_id)
            if (
                current != lease
                or not current.is_live(now, reading)
            ):
                raise MachineLeaseLost(
                    "cannot release a lost or fenced machine authority"
                )
            self._leases[lease.machine_id] = MachineLease(
                lease.machine_id,
                lease.owner_id,
                lease.epoch,
                lease.acquired_at,
                lease.expires_at,
                lease.host_identity_digest,
                lease.boot_identity_digest,
                True,
            )


class DirectoryMachineAuthority(InMemoryMachineAuthority):
    """Cross-process boot-aware durable authority using atomic JSON publication."""

    _CLOCK_ANCHOR_FILE = "clock-anchor.json"

    def __init__(
        self,
        directory: Path,
        *,
        clock: LeaseClockPort | None = None,
    ) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._guard = InterprocessFileLock(
            self.directory / "authority.guard.lock"
        )
        super().__init__(clock=clock)

    def _path(self, machine_id: str) -> Path:
        return self.directory / f"{canonical_digest(machine_id)}.json"

    def _clock_anchor_path(self) -> Path:
        return self.directory / self._CLOCK_ANCHOR_FILE

    @staticmethod
    def _encode_clock_anchor(anchor: _ClockAnchor) -> bytes:
        return canonical_bytes({
            "host_identity_digest": anchor.host_identity_digest,
            "boot_identity_digest": anchor.boot_identity_digest,
            "elapsed_seconds": anchor.elapsed_seconds,
            "logical_epoch_seconds": anchor.logical_epoch_seconds,
        })

    def _read_clock_anchor(self) -> _ClockAnchor | None:
        path = self._clock_anchor_path()
        if not path.exists():
            return None
        encoded = path.read_bytes()
        try:
            raw = strict_json_loads(encoded)
            if not isinstance(raw, dict) or set(raw) != {
                "host_identity_digest",
                "boot_identity_digest",
                "elapsed_seconds",
                "logical_epoch_seconds",
            }:
                raise ValueError("clock anchor fields are invalid")
            anchor = _ClockAnchor(
                str(raw["host_identity_digest"]),
                str(raw["boot_identity_digest"]),
                float(raw["elapsed_seconds"]),
                float(raw["logical_epoch_seconds"]),
            )
        except (OSError, TypeError, ValueError) as exc:
            raise MachineLeaseClockConflict(
                "machine authority clock anchor is malformed"
            ) from exc
        if canonical_bytes(raw) != encoded:
            raise MachineLeaseClockConflict(
                "machine authority clock anchor is not canonical"
            )
        return anchor

    def _write_clock_anchor(self, anchor: _ClockAnchor) -> None:
        atomic_replace_bytes(
            self._clock_anchor_path(),
            self._encode_clock_anchor(anchor),
        )

    def _authority_now_locked(
        self,
    ) -> tuple[float, LeaseClockReading]:
        reading = self._clock.read()
        anchor = self._read_clock_anchor()
        if anchor is None:
            anchor = _ClockAnchor.from_reading(reading)
            self._write_clock_anchor(anchor)
            return anchor.logical_epoch_seconds, reading
        if anchor.host_identity_digest != reading.host_identity_digest:
            raise MachineLeaseClockConflict(
                "machine authority belongs to a different host clock domain"
            )
        if anchor.boot_identity_digest != reading.boot_identity_digest:
            replacement = _ClockAnchor.from_reading(reading)
            self._write_clock_anchor(replacement)
            return replacement.logical_epoch_seconds, reading
        if reading.elapsed_seconds < anchor.elapsed_seconds:
            raise MachineLeaseClockConflict(
                "same-boot machine lease clock moved backwards"
            )
        return (
            anchor.logical_epoch_seconds
            + (reading.elapsed_seconds - anchor.elapsed_seconds),
            reading,
        )

    def _read(self, machine_id: str) -> MachineLease | None:
        path = self._path(machine_id)
        if not path.exists():
            return None
        encoded = path.read_bytes()
        try:
            raw = strict_json_loads(encoded)
        except ValueError as exc:
            raise MachineAuthorityError(
                "machine authority document is invalid"
            ) from exc
        if not isinstance(raw, dict):
            raise MachineAuthorityError(
                "machine authority document must be an object"
            )
        expected_fields = {
            "machine_id",
            "owner_id",
            "epoch",
            "acquired_at",
            "expires_at",
            "host_identity_digest",
            "boot_identity_digest",
            "released",
            "lease_digest",
        }
        if set(raw) != expected_fields:
            raise MachineAuthorityError(
                "machine authority document fields are invalid"
            )
        try:
            lease = MachineLease(
                str(raw["machine_id"]),
                str(raw["owner_id"]),
                raw["epoch"],
                raw["acquired_at"],
                raw["expires_at"],
                str(raw["host_identity_digest"]),
                str(raw["boot_identity_digest"]),
                raw["released"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MachineAuthorityError(
                "machine authority document is invalid"
            ) from exc
        if raw["lease_digest"] != lease.lease_digest:
            raise MachineAuthorityError(
                "machine authority document digest mismatch"
            )
        if canonical_bytes(raw) != encoded:
            raise MachineAuthorityError(
                "machine authority document is not canonical"
            )
        return lease

    @staticmethod
    def _encode(lease: MachineLease) -> bytes:
        return canonical_bytes({
            "machine_id": lease.machine_id,
            "owner_id": lease.owner_id,
            "epoch": lease.epoch,
            "acquired_at": lease.acquired_at,
            "expires_at": lease.expires_at,
            "host_identity_digest": lease.host_identity_digest,
            "boot_identity_digest": lease.boot_identity_digest,
            "released": lease.released,
            "lease_digest": lease.lease_digest,
        })

    def acquire(
        self,
        machine_id: str,
        owner_id: str,
        *,
        ttl_seconds: float = 30.0,
    ) -> MachineLease:
        if not machine_id.strip() or not owner_id.strip():
            raise ValueError(
                "machine authority machine_id and owner_id are required"
            )
        ttl = _ttl(ttl_seconds)
        with self._guard:
            now, reading = self._authority_now_locked()
            current = self._read(machine_id)
            if current is not None and current.is_live(now, reading):
                if current.owner_id != owner_id:
                    raise MachineLeaseBusy(
                        f"machine authority held by {current.owner_id}"
                    )
                return current
            lease = MachineLease(
                machine_id,
                owner_id,
                1 if current is None else current.epoch + 1,
                now,
                now + ttl,
                reading.host_identity_digest,
                reading.boot_identity_digest,
            )
            atomic_replace_bytes(self._path(machine_id), self._encode(lease))
            return lease

    def renew(
        self,
        lease: MachineLease,
        *,
        ttl_seconds: float = 30.0,
    ) -> MachineLease:
        ttl = _ttl(ttl_seconds)
        with self._guard:
            now, reading = self._authority_now_locked()
            current = self._read(lease.machine_id)
            if (
                current != lease
                or not current.is_live(now, reading)
            ):
                raise MachineLeaseLost(
                    "machine authority cannot be renewed"
                )
            renewed = MachineLease(
                lease.machine_id,
                lease.owner_id,
                lease.epoch,
                lease.acquired_at,
                now + ttl,
                reading.host_identity_digest,
                reading.boot_identity_digest,
            )
            atomic_replace_bytes(
                self._path(lease.machine_id),
                self._encode(renewed),
            )
            return renewed

    def assert_held(self, lease: MachineLease) -> MachineLease:
        with self._guard:
            now, reading = self._authority_now_locked()
            current = self._read(lease.machine_id)
            if (
                current != lease
                or not current.is_live(now, reading)
            ):
                raise MachineLeaseLost(
                    "machine authority is not held"
                )
            return current

    def release(self, lease: MachineLease) -> None:
        with self._guard:
            now, reading = self._authority_now_locked()
            current = self._read(lease.machine_id)
            if (
                current != lease
                or not current.is_live(now, reading)
            ):
                raise MachineLeaseLost(
                    "cannot release a lost or fenced machine authority"
                )
            revoked = MachineLease(
                lease.machine_id,
                lease.owner_id,
                lease.epoch,
                lease.acquired_at,
                lease.expires_at,
                lease.host_identity_digest,
                lease.boot_identity_digest,
                True,
            )
            atomic_replace_bytes(
                self._path(lease.machine_id),
                self._encode(revoked),
            )


__all__ = [
    "DirectoryMachineAuthority",
    "InMemoryMachineAuthority",
    "MachineAuthorityError",
    "MachineAuthorityPort",
    "MachineLease",
    "MachineLeaseBusy",
    "MachineLeaseClockConflict",
    "MachineLeaseLost",
]
