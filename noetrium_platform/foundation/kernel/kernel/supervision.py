"""Explicit parent/child Machine supervision contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from threading import RLock
from typing import Protocol, runtime_checkable

from .canonical import canonical_digest
from .contracts import ChildMachineLink


class ChildMachineStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


_TERMINAL = {
    ChildMachineStatus.COMPLETED,
    ChildMachineStatus.FAILED,
    ChildMachineStatus.CANCELED,
}


@dataclass(frozen=True, slots=True)
class ChildMachineRecord:
    link: ChildMachineLink
    status: ChildMachineStatus
    observed_revision: int
    result_ref: str | None = None
    error_ref: str | None = None
    record_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.link, ChildMachineLink):
            raise TypeError("child record link must be typed")
        if not isinstance(self.status, ChildMachineStatus):
            raise TypeError("child record status must be typed")
        if type(self.observed_revision) is not int or self.observed_revision < 0:
            raise ValueError("child observed_revision must be non-negative")
        for name, value in (("result_ref", self.result_ref), ("error_ref", self.error_ref)):
            if value is not None and (type(value) is not str or not value.strip()):
                raise ValueError(f"child {name} must be non-empty text")
        if self.status is ChildMachineStatus.COMPLETED and self.result_ref is None:
            raise ValueError("completed child must carry result_ref")
        if self.status is ChildMachineStatus.FAILED and self.error_ref is None:
            raise ValueError("failed child must carry error_ref")
        object.__setattr__(self, "record_digest", canonical_digest({
            "link": self.link,
            "status": self.status.value,
            "observed_revision": self.observed_revision,
            "result_ref": self.result_ref,
            "error_ref": self.error_ref,
        }))


class ChildMachinePending(RuntimeError):
    """The child has not reached a terminal lifecycle state."""


@runtime_checkable
class ChildMachineSupervisorPort(Protocol):
    def register(self, link: ChildMachineLink) -> ChildMachineRecord: ...
    def observe(self, record: ChildMachineRecord) -> ChildMachineRecord: ...
    def join(self, child_machine_id: str) -> ChildMachineRecord: ...
    def cancel(self, child_machine_id: str, error_ref: str) -> ChildMachineRecord: ...
    def list(self, parent_machine_id: str) -> tuple[ChildMachineRecord, ...]: ...


class InMemoryChildMachineSupervisor(ChildMachineSupervisorPort):
    """Strict lifecycle coordinator; it never writes a parent Journal."""

    durability = "process_local"

    def __init__(self) -> None:
        self._records: dict[str, ChildMachineRecord] = {}
        self._lock = RLock()

    def register(self, link: ChildMachineLink) -> ChildMachineRecord:
        if not isinstance(link, ChildMachineLink):
            raise TypeError("supervisor accepts ChildMachineLink")
        with self._lock:
            current = self._records.get(link.child_machine_id)
            if current is not None:
                if current.link.link_digest != link.link_digest:
                    raise ValueError("child identity is already linked differently")
                return current
            record = ChildMachineRecord(link, ChildMachineStatus.CREATED, 0)
            self._records[link.child_machine_id] = record
            return record

    def observe(self, record: ChildMachineRecord) -> ChildMachineRecord:
        if not isinstance(record, ChildMachineRecord):
            raise TypeError("supervisor accepts ChildMachineRecord")
        with self._lock:
            current = self._records.get(record.link.child_machine_id)
            if current is None:
                raise KeyError(record.link.child_machine_id)
            if current.link.link_digest != record.link.link_digest:
                raise ValueError("child link identity mismatch")
            if current.status in _TERMINAL:
                if current.record_digest != record.record_digest:
                    raise ChildMachinePending("terminal child record cannot change")
                return current
            if record.observed_revision < current.observed_revision:
                raise ChildMachinePending("child revision moved backwards")
            if record.status is ChildMachineStatus.CREATED and record.observed_revision > 0:
                raise ValueError("created child cannot report a positive revision")
            self._records[record.link.child_machine_id] = record
            return record

    def join(self, child_machine_id: str) -> ChildMachineRecord:
        if type(child_machine_id) is not str or not child_machine_id.strip():
            raise ValueError("child_machine_id is required")
        with self._lock:
            try:
                record = self._records[child_machine_id]
            except KeyError as exc:
                raise KeyError(child_machine_id) from exc
            if record.status not in _TERMINAL:
                raise ChildMachinePending(f"child is not terminal: {child_machine_id}")
            return record

    def cancel(self, child_machine_id: str, error_ref: str) -> ChildMachineRecord:
        if type(error_ref) is not str or not error_ref.strip():
            raise ValueError("cancel error_ref is required")
        with self._lock:
            try:
                current = self._records[child_machine_id]
            except KeyError as exc:
                raise KeyError(child_machine_id) from exc
            if current.status in _TERMINAL:
                return current
            return self.observe(ChildMachineRecord(
                current.link, ChildMachineStatus.CANCELED,
                current.observed_revision, error_ref=error_ref,
            ))

    def list(self, parent_machine_id: str) -> tuple[ChildMachineRecord, ...]:
        if type(parent_machine_id) is not str or not parent_machine_id.strip():
            raise ValueError("parent_machine_id is required")
        with self._lock:
            return tuple(
                self._records[key] for key in sorted(self._records)
                if self._records[key].link.parent_machine_id == parent_machine_id
            )


__all__ = [
    "ChildMachinePending",
    "ChildMachineRecord",
    "ChildMachineStatus",
    "ChildMachineSupervisorPort",
    "InMemoryChildMachineSupervisor",
]
