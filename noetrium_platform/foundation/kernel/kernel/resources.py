"""Typed resource admission and bounded execution reservations."""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Protocol, runtime_checkable

from .canonical import canonical_digest


def _nonnegative(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class ResourceBudget:
    cpu_millis: int = 0
    memory_bytes: int = 0
    concurrency_slots: int = 0
    token_units: int = 0
    budget_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("cpu_millis", "memory_bytes", "concurrency_slots", "token_units"):
            _nonnegative(getattr(self, name), name)
        if not any((self.cpu_millis, self.memory_bytes, self.concurrency_slots, self.token_units)):
            raise ValueError("resource budget must reserve at least one resource")
        object.__setattr__(self, "budget_digest", canonical_digest({
            "cpu_millis": self.cpu_millis,            "memory_bytes": self.memory_bytes,
            "concurrency_slots": self.concurrency_slots,
            "token_units": self.token_units,
        }))


@dataclass(frozen=True, slots=True)
class ResourceCapacity:
    cpu_millis: int
    memory_bytes: int
    concurrency_slots: int
    token_units: int
    capacity_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("cpu_millis", "memory_bytes", "concurrency_slots", "token_units"):
            _nonnegative(getattr(self, name), name)
        object.__setattr__(self, "capacity_digest", canonical_digest({
            "cpu_millis": self.cpu_millis,
            "memory_bytes": self.memory_bytes,
            "concurrency_slots": self.concurrency_slots,
            "token_units": self.token_units,
        }))


@dataclass(frozen=True, slots=True)
class ResourceLease:
    lease_id: str
    owner_id: str
    budget: ResourceBudget
    lease_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.lease_id) is not str or not self.lease_id.strip():
            raise ValueError("resource lease_id is required")
        if type(self.owner_id) is not str or not self.owner_id.strip():
            raise ValueError("resource owner_id is required")
        if not isinstance(self.budget, ResourceBudget):
            raise TypeError("resource lease budget must be typed")
        object.__setattr__(self, "lease_digest", canonical_digest({
            "lease_id": self.lease_id,
            "owner_id": self.owner_id,
            "budget": self.budget,
        }))


@runtime_checkable
class ResourceSchedulerPort(Protocol):
    def acquire(self, owner_id: str, budget: ResourceBudget) -> ResourceLease: ...
    def release(self, lease: ResourceLease) -> None: ...
    def available(self) -> ResourceCapacity: ...
    def active(self) -> tuple[ResourceLease, ...]: ...


class ResourceAdmissionError(RuntimeError):
    """A request exceeds the currently available execution capacity."""


class InMemoryResourceScheduler(ResourceSchedulerPort):
    """Deterministic bounded scheduler for composition and local execution."""

    durability = "process_local"

    def __init__(self, capacity: ResourceCapacity) -> None:
        if not isinstance(capacity, ResourceCapacity):
            raise TypeError("scheduler capacity must be typed")
        self.capacity = capacity
        self._active: dict[str, ResourceLease] = {}
        self._lock = RLock()

    @staticmethod
    def _fits(available: ResourceCapacity, budget: ResourceBudget) -> bool:
        return (
            available.cpu_millis >= budget.cpu_millis
            and available.memory_bytes >= budget.memory_bytes
            and available.concurrency_slots >= budget.concurrency_slots
            and available.token_units >= budget.token_units
        )

    def available(self) -> ResourceCapacity:
        with self._lock:
            used = ResourceCapacity(
                sum(item.budget.cpu_millis for item in self._active.values()),
                sum(item.budget.memory_bytes for item in self._active.values()),
                sum(item.budget.concurrency_slots for item in self._active.values()),
                sum(item.budget.token_units for item in self._active.values()),
            )
            return ResourceCapacity(
                self.capacity.cpu_millis - used.cpu_millis,
                self.capacity.memory_bytes - used.memory_bytes,
                self.capacity.concurrency_slots - used.concurrency_slots,
                self.capacity.token_units - used.token_units,
            )

    def acquire(self, owner_id: str, budget: ResourceBudget) -> ResourceLease:
        if type(owner_id) is not str or not owner_id.strip():
            raise ValueError("resource owner_id is required")
        if not isinstance(budget, ResourceBudget):
            raise TypeError("resource budget must be typed")
        with self._lock:
            prior = next((item for item in self._active.values()
                          if item.owner_id == owner_id), None)
            if prior is not None:
                if prior.budget != budget:
                    raise ResourceAdmissionError("owner already has a different reservation")
                return prior
            available = self.available()
            if not self._fits(available, budget):
                raise ResourceAdmissionError(
                    f"resource capacity exceeded for {owner_id}: "
                    f"requested={budget.budget_digest} available={available.capacity_digest}"
                )
            lease_id = canonical_digest({
                "owner_id": owner_id,
                "budget": budget,
                "active": tuple(sorted(self._active)),
            })
            lease = ResourceLease(lease_id, owner_id, budget)
            self._active[lease_id] = lease
            return lease

    def release(self, lease: ResourceLease) -> None:
        if not isinstance(lease, ResourceLease):
            raise TypeError("resource release expects ResourceLease")
        with self._lock:
            current = self._active.get(lease.lease_id)
            if current is None:
                raise ResourceAdmissionError("resource lease is not active")
            if current.lease_digest != lease.lease_digest:
                raise ResourceAdmissionError("resource lease identity conflict")
            del self._active[lease.lease_id]

    def active(self) -> tuple[ResourceLease, ...]:
        with self._lock:
            return tuple(self._active[key] for key in sorted(self._active))


__all__ = [
    "InMemoryResourceScheduler",
    "ResourceAdmissionError",
    "ResourceBudget",
    "ResourceCapacity",
    "ResourceLease",
    "ResourceSchedulerPort",
]
