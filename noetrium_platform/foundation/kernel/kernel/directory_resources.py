"""Crash-durable, cross-process resource scheduler."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .canonical import canonical_bytes, canonical_digest, strict_json_loads
from .durability import InterprocessFileLock, atomic_replace_bytes
from .resources import (
    InMemoryResourceScheduler,
    ResourceAdmissionError,
    ResourceBudget,
    ResourceCapacity,
    ResourceLease,
    ResourceSchedulerPort,
)


def _budget_document(budget: ResourceBudget) -> dict[str, int]:
    return {
        "cpu_millis": budget.cpu_millis,
        "memory_bytes": budget.memory_bytes,
        "concurrency_slots": budget.concurrency_slots,
        "token_units": budget.token_units,
    }


def _lease_document(lease: ResourceLease) -> dict[str, object]:
    return {
        "lease_id": lease.lease_id,
        "owner_id": lease.owner_id,
        "budget": _budget_document(lease.budget),
        "lease_digest": lease.lease_digest,
    }


class DirectoryResourceScheduler(ResourceSchedulerPort):
    """Interprocess reservation ledger with atomic lease publication."""

    durability = "crash_durable"

    def __init__(self, root: Path, capacity: ResourceCapacity) -> None:
        if not isinstance(capacity, ResourceCapacity):
            raise TypeError("scheduler capacity must be typed")
        self.root = Path(root)
        self.leases = self.root / "leases"
        self.locks = self.root / "locks"
        self.leases.mkdir(parents=True, exist_ok=True)
        self.locks.mkdir(parents=True, exist_ok=True)
        self.capacity = capacity
        self._capacity_path = self.root / "capacity.json"
        self._global_lock = self.locks / "scheduler.lock"
        if self._capacity_path.exists():
            stored = self._read_capacity()
            if stored != capacity:
                raise ResourceAdmissionError("resource capacity conflicts with durable scheduler")
        else:
            atomic_replace_bytes(self._capacity_path, canonical_bytes({
                "cpu_millis": capacity.cpu_millis,
                "memory_bytes": capacity.memory_bytes,
                "concurrency_slots": capacity.concurrency_slots,
                "token_units": capacity.token_units,
                "capacity_digest": capacity.capacity_digest,
            }))
    def _read_capacity(self) -> ResourceCapacity:
        try:
            value = strict_json_loads(self._capacity_path.read_bytes())
            if not isinstance(value, dict) or set(value) != {
                "cpu_millis", "memory_bytes", "concurrency_slots",
                "token_units", "capacity_digest",
            }:
                raise ResourceAdmissionError("resource capacity record is corrupt")
            capacity = ResourceCapacity(
                value["cpu_millis"], value["memory_bytes"],
                value["concurrency_slots"], value["token_units"],
            )
            if capacity.capacity_digest != value["capacity_digest"]:
                raise ResourceAdmissionError("resource capacity digest mismatch")
            return capacity
        except ResourceAdmissionError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise ResourceAdmissionError("cannot read resource capacity") from exc

    @staticmethod
    def _decode_lease(value: object) -> ResourceLease:
        if not isinstance(value, dict) or set(value) != {
            "lease_id", "owner_id", "budget", "lease_digest",
        }:
            raise ResourceAdmissionError("resource lease record is corrupt")
        budget = value["budget"]
        if not isinstance(budget, dict) or set(budget) != {
            "cpu_millis", "memory_bytes", "concurrency_slots", "token_units",
        }:
            raise ResourceAdmissionError("resource budget record is corrupt")
        lease = ResourceLease(
            value["lease_id"], value["owner_id"],
            ResourceBudget(
                budget["cpu_millis"], budget["memory_bytes"],
                budget["concurrency_slots"], budget["token_units"],
            ),
        )
        if lease.lease_id != value["lease_id"] or lease.lease_digest != value["lease_digest"]:
            raise ResourceAdmissionError("resource lease digest mismatch")
        return lease

    def _read_leases(self) -> tuple[ResourceLease, ...]:
        leases: list[ResourceLease] = []
        for path in sorted(self.leases.glob("*.json")):
            try:
                raw = path.read_bytes()
                value = strict_json_loads(raw)
                if canonical_bytes(value) != raw:
                    raise ResourceAdmissionError("resource lease is not canonical")
                lease = self._decode_lease(value)
            except ResourceAdmissionError:
                raise
            except (OSError, TypeError, ValueError) as exc:
                raise ResourceAdmissionError(f"cannot read resource lease: {path}") from exc
            if path.stem != lease.lease_id:
                raise ResourceAdmissionError("resource lease filename identity mismatch")
            leases.append(lease)
        return tuple(leases)

    @staticmethod
    def _available(capacity: ResourceCapacity, leases: Iterable[ResourceLease]) -> ResourceCapacity:
        items = tuple(leases)
        return ResourceCapacity(
            capacity.cpu_millis - sum(item.budget.cpu_millis for item in items),
            capacity.memory_bytes - sum(item.budget.memory_bytes for item in items),
            capacity.concurrency_slots - sum(item.budget.concurrency_slots for item in items),
            capacity.token_units - sum(item.budget.token_units for item in items),
        )

    def available(self) -> ResourceCapacity:
        with InterprocessFileLock(self._global_lock):
            return self._available(self.capacity, self._read_leases())

    def acquire(self, owner_id: str, budget: ResourceBudget) -> ResourceLease:
        if type(owner_id) is not str or not owner_id.strip():
            raise ValueError("resource owner_id is required")
        if not isinstance(budget, ResourceBudget):
            raise TypeError("resource budget must be typed")
        with InterprocessFileLock(self._global_lock):
            leases = self._read_leases()
            existing = next((item for item in leases if item.owner_id == owner_id), None)
            if existing is not None:
                if existing.budget != budget:
                    raise ResourceAdmissionError("owner already has a different reservation")
                return existing
            available = self._available(self.capacity, leases)
            if any((
                available.cpu_millis < budget.cpu_millis,
                available.memory_bytes < budget.memory_bytes,
                available.concurrency_slots < budget.concurrency_slots,
                available.token_units < budget.token_units,
            )):
                raise ResourceAdmissionError("resource capacity exceeded")
            lease_id = canonical_digest({
                "owner_id": owner_id,
                "budget": budget,
                "active": tuple(sorted(item.lease_id for item in leases)),
            })
            lease = ResourceLease(lease_id, owner_id, budget)
            atomic_replace_bytes(
                self.leases / f"{lease.lease_id}.json",
                canonical_bytes(_lease_document(lease)),
            )
            return lease
    def release(self, lease: ResourceLease) -> None:
        if not isinstance(lease, ResourceLease):
            raise TypeError("resource release expects ResourceLease")
        with InterprocessFileLock(self._global_lock):
            current = next(
                (item for item in self._read_leases() if item.lease_id == lease.lease_id),
                None,
            )
            if current is None:
                raise ResourceAdmissionError("resource lease is not active")
            if current.lease_digest != lease.lease_digest:
                raise ResourceAdmissionError("resource lease identity conflict")
            (self.leases / f"{lease.lease_id}.json").unlink()

    def active(self) -> tuple[ResourceLease, ...]:
        with InterprocessFileLock(self._global_lock):
            return self._read_leases()


__all__ = ["DirectoryResourceScheduler"]
