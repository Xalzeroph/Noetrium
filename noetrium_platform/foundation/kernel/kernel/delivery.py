"""Inbox/outbox contracts for cross-machine command delivery.

The ledger is intentionally separate from the state journal: a committed
transition is fact even when delivery is delayed or unknown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Protocol, runtime_checkable

from .canonical import canonical_digest
from .machine import MachineCommand, MachineCommit, MachineConflict


class DeliveryStatus:
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class MachineEnvelope:
    source_machine_id: str
    source_commit_id: str
    command: MachineCommand
    envelope_id: str = field(init=False)
    envelope_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.source_machine_id) is not str or not self.source_machine_id.strip():
            raise ValueError("envelope source_machine_id is required")
        if type(self.source_commit_id) is not str or not self.source_commit_id.strip():
            raise ValueError("envelope source_commit_id is required")
        if not isinstance(self.command, MachineCommand):
            raise TypeError("envelope command must be MachineCommand")
        object.__setattr__(
            self,
            "envelope_id",
            canonical_digest({
                "source_machine_id": self.source_machine_id,
                "source_commit_id": self.source_commit_id,
                "command_id": self.command.command_id,
                "command_digest": self.command.payload_digest,
            }),
        )
        object.__setattr__(
            self,
            "envelope_digest",
            canonical_digest({
                "envelope_id": self.envelope_id,
                "source_machine_id": self.source_machine_id,
                "source_commit_id": self.source_commit_id,
                "command": self.command,
            }),
        )


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    envelope_id: str
    envelope_digest: str
    status: str
    attempt: int
    detail: str | None = None
    receipt_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.envelope_id) is not str or not self.envelope_id.strip():
            raise ValueError("delivery envelope_id is required")
        if type(self.envelope_digest) is not str or not self.envelope_digest.strip():
            raise ValueError("delivery envelope_digest is required")
        if self.status not in {
            DeliveryStatus.PENDING, DeliveryStatus.DELIVERED,
            DeliveryStatus.FAILED, DeliveryStatus.UNKNOWN,
        }:
            raise ValueError("unsupported delivery status")
        if type(self.attempt) is not int or self.attempt < 0:
            raise ValueError("delivery attempt must be non-negative")
        if self.detail is not None and type(self.detail) is not str:
            raise TypeError("delivery detail must be text when provided")
        object.__setattr__(self, "receipt_digest", canonical_digest({
            "envelope_id": self.envelope_id,
            "envelope_digest": self.envelope_digest,
            "status": self.status,
            "attempt": self.attempt,
            "detail": self.detail,
        }))


@runtime_checkable
class MachineOutboxPort(Protocol):
    def enqueue(self, commit: MachineCommit) -> tuple[MachineEnvelope, ...]: ...
    def pending(self) -> tuple[MachineEnvelope, ...]: ...
    def mark(self, receipt: DeliveryReceipt) -> DeliveryReceipt: ...
    def reconcile(self, commits: tuple[MachineCommit, ...]) -> tuple[MachineEnvelope, ...]: ...


@runtime_checkable
class MachineInboxPort(Protocol):
    def accept(self, envelope: MachineEnvelope) -> bool: ...
    def contains(self, envelope_id: str) -> bool: ...


class InMemoryMachineOutbox(MachineOutboxPort):
    """Idempotent process-local outbox; reconcile repairs commit/enqueue gaps."""

    durability = "process_local"

    def __init__(self) -> None:
        self._envelopes: dict[str, MachineEnvelope] = {}
        self._receipts: dict[str, DeliveryReceipt] = {}
        self._lock = RLock()

    def enqueue(self, commit: MachineCommit) -> tuple[MachineEnvelope, ...]:
        if not isinstance(commit, MachineCommit):
            raise TypeError("outbox accepts MachineCommit")
        created: list[MachineEnvelope] = []
        with self._lock:
            for command in commit.emitted_commands:
                envelope = MachineEnvelope(
                    source_machine_id=commit.machine_id,
                    source_commit_id=commit.commit_id,
                    command=command,
                )
                prior = self._envelopes.get(envelope.envelope_id)
                if prior is not None and prior.envelope_digest != envelope.envelope_digest:
                    raise MachineConflict("outbox envelope identity collision")
                self._envelopes[envelope.envelope_id] = envelope
                self._receipts.setdefault(
                    envelope.envelope_id,
                    DeliveryReceipt(
                        envelope_id=envelope.envelope_id,
                        envelope_digest=envelope.envelope_digest,
                        status=DeliveryStatus.PENDING,
                        attempt=0,
                    ),
                )
                created.append(envelope)
        return tuple(created)
    def pending(self) -> tuple[MachineEnvelope, ...]:
        with self._lock:
            return tuple(
                envelope for envelope in self._envelopes.values()
                if self._receipts[envelope.envelope_id].status
                in {DeliveryStatus.PENDING, DeliveryStatus.UNKNOWN, DeliveryStatus.FAILED}
            )

    def mark(self, receipt: DeliveryReceipt) -> DeliveryReceipt:
        if not isinstance(receipt, DeliveryReceipt):
            raise TypeError("outbox accepts DeliveryReceipt")
        with self._lock:
            envelope = self._envelopes.get(receipt.envelope_id)
            if envelope is None:
                raise KeyError(receipt.envelope_id)
            if envelope.envelope_digest != receipt.envelope_digest:
                raise MachineConflict("delivery receipt envelope digest mismatch")
            current = self._receipts[receipt.envelope_id]
            if receipt.attempt < current.attempt:
                raise MachineConflict("delivery attempt cannot move backwards")
            if receipt.attempt == current.attempt and receipt != current:
                raise MachineConflict("delivery receipt conflict at same attempt")
            self._receipts[receipt.envelope_id] = receipt
            return receipt

    def reconcile(self, commits: tuple[MachineCommit, ...]) -> tuple[MachineEnvelope, ...]:
        if type(commits) is not tuple or any(not isinstance(item, MachineCommit) for item in commits):
            raise TypeError("outbox reconcile expects typed commit tuple")
        result: list[MachineEnvelope] = []
        for commit in commits:
            result.extend(self.enqueue(commit))
        return tuple(result)


class InMemoryMachineInbox(MachineInboxPort):
    """Receiver-side dedupe barrier; business handling happens after accept."""

    durability = "process_local"

    def __init__(self) -> None:
        self._envelopes: dict[str, MachineEnvelope] = {}
        self._lock = RLock()

    def accept(self, envelope: MachineEnvelope) -> bool:
        if not isinstance(envelope, MachineEnvelope):
            raise TypeError("inbox accepts MachineEnvelope")
        with self._lock:
            prior = self._envelopes.get(envelope.envelope_id)
            if prior is not None:
                if prior.envelope_digest != envelope.envelope_digest:
                    raise MachineConflict("inbox envelope identity collision")
                return False
            self._envelopes[envelope.envelope_id] = envelope
            return True

    def contains(self, envelope_id: str) -> bool:
        if type(envelope_id) is not str or not envelope_id.strip():
            raise ValueError("inbox envelope_id is required")
        with self._lock:
            return envelope_id in self._envelopes


__all__ = [
    "DeliveryReceipt",
    "DeliveryStatus",
    "InMemoryMachineInbox",
    "InMemoryMachineOutbox",
    "MachineEnvelope",
    "MachineInboxPort",
    "MachineOutboxPort",
]
