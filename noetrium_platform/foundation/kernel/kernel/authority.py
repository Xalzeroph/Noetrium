"""Machine authority lease with monotonic epoch fencing.

This is deliberately distinct from resource and recovery leases: it protects
the Machine Kernel commit authority itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
from threading import RLock
import time
from typing import Callable, Protocol, runtime_checkable

from .canonical import canonical_bytes, canonical_digest, strict_json_loads

class MachineAuthorityError(RuntimeError):
    """Base error for machine authority violations."""


class MachineLeaseBusy(MachineAuthorityError):
    """Another live owner currently has the machine authority."""


class MachineLeaseLost(MachineAuthorityError):
    """The caller's lease is missing, expired, or fenced by a newer epoch."""


@dataclass(frozen=True, slots=True)
class MachineLease:
    machine_id: str
    owner_id: str
    epoch: int
    acquired_at: float
    expires_at: float
    released: bool = False
    lease_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.machine_id.strip() or not self.owner_id.strip():
            raise ValueError("machine lease identity fields are required")
        if type(self.epoch) is not int or self.epoch < 1:
            raise ValueError("machine lease epoch must be positive")
        for name, value in (("acquired_at", self.acquired_at), ("expires_at", self.expires_at)):
            if not math.isfinite(float(value)):
                raise ValueError(f"machine lease {name} must be finite")
        if type(self.released) is not bool:
            raise TypeError("machine lease released must be bool")
        if self.expires_at <= self.acquired_at:
            raise ValueError("machine lease expiry must be after acquisition")
        object.__setattr__(self, "lease_digest", canonical_digest({
            "machine_id": self.machine_id,
            "owner_id": self.owner_id,
            "epoch": self.epoch,
            "acquired_at": self.acquired_at,
            "expires_at": self.expires_at,
            "released": self.released,
        }))

    def is_live(self, now: float) -> bool:
        return not self.released and self.expires_at > float(now)


@runtime_checkable
class MachineAuthorityPort(Protocol):
    def acquire(self, machine_id: str, owner_id: str, *, ttl_seconds: float = 30.0, now: float | None = None) -> MachineLease: ...
    def renew(self, lease: MachineLease, *, ttl_seconds: float = 30.0, now: float | None = None) -> MachineLease: ...
    def assert_held(self, lease: MachineLease, *, now: float | None = None) -> MachineLease: ...
    def release(self, lease: MachineLease) -> None: ...


def _time(now: float | None) -> float:
    value = time.time() if now is None else float(now)
    if not math.isfinite(value):
        raise ValueError("machine authority time must be finite")
    return value


def _ttl(ttl_seconds: float) -> float:
    value = float(ttl_seconds)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("machine authority ttl_seconds must be finite and positive")
    return value


class InMemoryMachineAuthority:
    """Deterministic authority provider useful for tests and single-process runs."""

    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.time
        self._leases: dict[str, MachineLease] = {}
        self._lock = RLock()

    def _now(self, now: float | None) -> float:
        return _time(self._clock() if now is None else now)

    def acquire(self, machine_id: str, owner_id: str, *, ttl_seconds: float = 30.0, now: float | None = None) -> MachineLease:
        if not machine_id.strip() or not owner_id.strip():
            raise ValueError("machine authority machine_id and owner_id are required")
        t, ttl = self._now(now), _ttl(ttl_seconds)
        with self._lock:
            current = self._leases.get(machine_id)
            if current is not None and current.is_live(t):
                if current.owner_id != owner_id:
                    raise MachineLeaseBusy(f"machine authority held by {current.owner_id}")
                return current
            epoch = 1 if current is None else current.epoch + 1
            lease = MachineLease(machine_id, owner_id, epoch, t, t + ttl)
            self._leases[machine_id] = lease
            return lease

    def renew(self, lease: MachineLease, *, ttl_seconds: float = 30.0, now: float | None = None) -> MachineLease:
        t, ttl = self._now(now), _ttl(ttl_seconds)
        with self._lock:
            current = self._leases.get(lease.machine_id)
            if current != lease or not current.is_live(t):
                raise MachineLeaseLost("machine authority cannot be renewed")
            renewed = MachineLease(lease.machine_id, lease.owner_id, lease.epoch, lease.acquired_at, t + ttl)
            self._leases[lease.machine_id] = renewed
            return renewed

    def assert_held(self, lease: MachineLease, *, now: float | None = None) -> MachineLease:
        t = self._now(now)
        with self._lock:
            current = self._leases.get(lease.machine_id)
            if current != lease or not current.is_live(t):
                raise MachineLeaseLost("machine authority is not held")
            return current

    def release(self, lease: MachineLease) -> None:
        with self._lock:
            current = self._leases.get(lease.machine_id)
            if current != lease:
                raise MachineLeaseLost("cannot release a fenced machine authority")
            self._leases[lease.machine_id] = MachineLease(
                lease.machine_id, lease.owner_id, lease.epoch,
                lease.acquired_at, lease.expires_at, True,
            )


class DirectoryMachineAuthority(InMemoryMachineAuthority):
    """Cross-process durable authority provider using atomic JSON publication."""

    def __init__(self, directory: Path, *, clock: Callable[[], float] | None = None) -> None:
        self.directory = directory
        from .durability.file_lock import InterprocessFileLock
        self.directory.mkdir(parents=True, exist_ok=True)
        self._guard = InterprocessFileLock(self.directory / "authority.guard.lock")
        super().__init__(clock=clock)

    def _path(self, machine_id: str) -> Path:
        return self.directory / f"{canonical_digest(machine_id)}.json"

    def _read(self, machine_id: str) -> MachineLease | None:
        path = self._path(machine_id)
        if not path.exists():
            return None
        raw = strict_json_loads(path.read_bytes())
        if not isinstance(raw, dict):
            raise MachineAuthorityError("machine authority document must be an object")
        try:
            return MachineLease(
                raw["machine_id"], raw["owner_id"], raw["epoch"],
                raw["acquired_at"], raw["expires_at"], raw.get("released", False),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MachineAuthorityError("machine authority document is invalid") from exc

    @staticmethod
    def _encode(lease: MachineLease) -> bytes:
        return canonical_bytes({
            "machine_id": lease.machine_id,
            "owner_id": lease.owner_id,
            "epoch": lease.epoch,
            "acquired_at": lease.acquired_at,
            "expires_at": lease.expires_at,
            "released": lease.released,
            "lease_digest": lease.lease_digest,
        })

    def acquire(self, machine_id: str, owner_id: str, *, ttl_seconds: float = 30.0, now: float | None = None) -> MachineLease:
        with self._guard:
            current = self._read(machine_id)
            t, ttl = _time(self._clock() if now is None else now), _ttl(ttl_seconds)
            if current is not None and current.is_live(t):
                if current.owner_id != owner_id:
                    raise MachineLeaseBusy(f"machine authority held by {current.owner_id}")
                return current
            lease = MachineLease(machine_id, owner_id, 1 if current is None else current.epoch + 1, t, t + ttl)
            from .durability.durable_file import atomic_replace_bytes
            atomic_replace_bytes(self._path(machine_id), self._encode(lease))
            return lease

    def renew(self, lease: MachineLease, *, ttl_seconds: float = 30.0, now: float | None = None) -> MachineLease:
        with self._guard:
            current = self._read(lease.machine_id)
            t, ttl = _time(self._clock() if now is None else now), _ttl(ttl_seconds)
            if current != lease or not current.is_live(t):
                raise MachineLeaseLost("machine authority cannot be renewed")
            renewed = MachineLease(lease.machine_id, lease.owner_id, lease.epoch, lease.acquired_at, t + ttl)
            from .durability.durable_file import atomic_replace_bytes
            atomic_replace_bytes(self._path(lease.machine_id), self._encode(renewed))
            return renewed

    def assert_held(self, lease: MachineLease, *, now: float | None = None) -> MachineLease:
        with self._guard:
            current = self._read(lease.machine_id)
            t = _time(self._clock() if now is None else now)
            if current != lease or not current.is_live(t):
                raise MachineLeaseLost("machine authority is not held")
            return current

    def release(self, lease: MachineLease) -> None:
        with self._guard:
            current = self._read(lease.machine_id)
            if current != lease:
                raise MachineLeaseLost("cannot release a fenced machine authority")
            from .durability.durable_file import atomic_replace_bytes
            revoked = MachineLease(
                lease.machine_id, lease.owner_id, lease.epoch,
                lease.acquired_at, lease.expires_at, True,
            )
            atomic_replace_bytes(self._path(lease.machine_id), self._encode(revoked))


__all__ = [
    "DirectoryMachineAuthority",
    "InMemoryMachineAuthority",
    "MachineAuthorityError",
    "MachineAuthorityPort",
    "MachineLease",
    "MachineLeaseBusy",
    "MachineLeaseLost",
]
