"""Crash-durable Machine inbox/outbox providers.

The provider persists canonical envelopes and receipts separately from the
Machine journal.  It therefore supports at-least-once delivery without
pretending that dispatch and state commit are one transaction.
"""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any

from .canonical import canonical_bytes, strict_json_loads, thaw_json
from .delivery import (
    DeliveryReceipt,
    DeliveryStatus,
    MachineEnvelope,
    MachineInboxPort,
    MachineOutboxPort,
)
from .durability import InterprocessFileLock, atomic_replace_bytes
from .machine import MachineCommand, MachineCommit, MachineConflict, MachineIntegrityError


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise MachineIntegrityError(f"{label} must be non-empty text")
    return value


def _command_document(command: MachineCommand) -> dict[str, object]:
    return {
        "command_id": command.command_id,
        "machine_id": command.machine_id,
        "expected_revision": command.expected_revision,
        "kind": command.kind,
        "payload": thaw_json(command.payload),
        "scope": list(command.scope),
        "deadline_at": command.deadline_at,
        "parent_command_id": command.parent_command_id,
        "idempotency_key": command.idempotency_key,
        "payload_digest": command.payload_digest,
    }


def _decode_command(value: object) -> MachineCommand:
    if not isinstance(value, dict):
        raise MachineIntegrityError("delivery command must be an object")
    required = {
        "command_id", "machine_id", "expected_revision", "kind", "payload",
        "scope", "deadline_at", "parent_command_id", "idempotency_key",
        "payload_digest",
    }
    if set(value) != required:
        raise MachineIntegrityError("delivery command fields are not exact")
    scope = value["scope"]
    if not isinstance(scope, list):
        raise MachineIntegrityError("delivery command scope must be a list")
    command = MachineCommand(
        command_id=_text(value["command_id"], "command_id"),
        machine_id=_text(value["machine_id"], "machine_id"),
        expected_revision=value["expected_revision"],  # type: ignore[arg-type]
        kind=_text(value["kind"], "kind"),
        payload=value["payload"],  # type: ignore[arg-type]
        scope=tuple(_text(item, "scope item") for item in scope),
        deadline_at=value["deadline_at"],  # type: ignore[arg-type]
        parent_command_id=value["parent_command_id"],  # type: ignore[arg-type]
        idempotency_key=value["idempotency_key"],  # type: ignore[arg-type]
    )
    if command.payload_digest != _text(value["payload_digest"], "payload_digest"):
        raise MachineIntegrityError("delivery command digest mismatch")
    return command


def _envelope_document(envelope: MachineEnvelope) -> dict[str, object]:
    return {
        "source_machine_id": envelope.source_machine_id,
        "source_commit_id": envelope.source_commit_id,
        "command": _command_document(envelope.command),
        "envelope_id": envelope.envelope_id,
        "envelope_digest": envelope.envelope_digest,
    }


def _decode_envelope(value: object) -> MachineEnvelope:
    if not isinstance(value, dict):
        raise MachineIntegrityError("delivery envelope must be an object")
    required = {
        "source_machine_id", "source_commit_id", "command",
        "envelope_id", "envelope_digest",
    }
    if set(value) != required:
        raise MachineIntegrityError("delivery envelope fields are not exact")
    envelope = MachineEnvelope(
        source_machine_id=_text(value["source_machine_id"], "source_machine_id"),
        source_commit_id=_text(value["source_commit_id"], "source_commit_id"),
        command=_decode_command(value["command"]),
    )
    if envelope.envelope_id != _text(value["envelope_id"], "envelope_id"):
        raise MachineIntegrityError("delivery envelope identity mismatch")
    if envelope.envelope_digest != _text(value["envelope_digest"], "envelope_digest"):
        raise MachineIntegrityError("delivery envelope digest mismatch")
    return envelope


def _receipt_document(receipt: DeliveryReceipt) -> dict[str, object]:
    return {
        "envelope_id": receipt.envelope_id,
        "envelope_digest": receipt.envelope_digest,
        "status": receipt.status,
        "attempt": receipt.attempt,
        "detail": receipt.detail,
        "receipt_digest": receipt.receipt_digest,
    }


def _decode_receipt(value: object) -> DeliveryReceipt:
    if not isinstance(value, dict):
        raise MachineIntegrityError("delivery receipt must be an object")
    required = {
        "envelope_id", "envelope_digest", "status", "attempt",
        "detail", "receipt_digest",
    }
    if set(value) != required:
        raise MachineIntegrityError("delivery receipt fields are not exact")
    receipt = DeliveryReceipt(
        envelope_id=_text(value["envelope_id"], "envelope_id"),
        envelope_digest=_text(value["envelope_digest"], "envelope_digest"),
        status=_text(value["status"], "status"),
        attempt=value["attempt"],  # type: ignore[arg-type]
        detail=value["detail"],  # type: ignore[arg-type]
    )
    if receipt.receipt_digest != _text(value["receipt_digest"], "receipt_digest"):
        raise MachineIntegrityError("delivery receipt digest mismatch")
    return receipt


class _DirectoryDeliveryStore:
    durability = "crash_durable"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.root / ".delivery.lock"
        self._lock = RLock()

    def _read(self, path: Path) -> Any:
        try:
            raw = path.read_bytes()
            value = strict_json_loads(raw)
            if canonical_bytes(value) != raw:
                raise MachineIntegrityError("delivery document is not canonical JSON")
            return value
        except MachineIntegrityError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise MachineIntegrityError(f"cannot read delivery document: {path}") from exc

    def _write(self, path: Path, value: object) -> None:
        atomic_replace_bytes(path, canonical_bytes(value))

    def _guard(self) -> InterprocessFileLock:
        return InterprocessFileLock(self.lock_path)


class DirectoryMachineOutbox(_DirectoryDeliveryStore, MachineOutboxPort):
    """Crash-durable outbox with canonical envelope and receipt files."""

    def __init__(self, root: Path) -> None:
        super().__init__(Path(root) / "outbox")
        self.envelopes = self.root / "envelopes"
        self.receipts = self.root / "receipts"
        self.envelopes.mkdir(exist_ok=True)
        self.receipts.mkdir(exist_ok=True)

    def _envelope_path(self, envelope_id: str) -> Path:
        return self.envelopes / f"{envelope_id}.json"

    def _receipt_path(self, envelope_id: str) -> Path:
        return self.receipts / f"{envelope_id}.json"

    def _load_envelope(self, envelope_id: str) -> MachineEnvelope | None:
        path = self._envelope_path(envelope_id)
        return None if not path.exists() else _decode_envelope(self._read(path))

    def _load_receipt(self, envelope: MachineEnvelope) -> DeliveryReceipt:
        path = self._receipt_path(envelope.envelope_id)
        if not path.exists():
            return DeliveryReceipt(
                envelope_id=envelope.envelope_id,
                envelope_digest=envelope.envelope_digest,
                status=DeliveryStatus.PENDING,
                attempt=0,
            )
        receipt = _decode_receipt(self._read(path))
        if (
            receipt.envelope_id != envelope.envelope_id
            or receipt.envelope_digest != envelope.envelope_digest
        ):
            raise MachineIntegrityError("delivery receipt does not match envelope")
        return receipt


    def enqueue(self, commit: MachineCommit) -> tuple[MachineEnvelope, ...]:
        if not isinstance(commit, MachineCommit):
            raise TypeError("outbox accepts MachineCommit")
        created: list[MachineEnvelope] = []
        with self._lock, self._guard():
            for command in commit.emitted_commands:
                envelope = MachineEnvelope(
                    source_machine_id=commit.machine_id,
                    source_commit_id=commit.commit_id,
                    command=command,
                )
                prior = self._load_envelope(envelope.envelope_id)
                if prior is not None and prior.envelope_digest != envelope.envelope_digest:
                    raise MachineConflict("outbox envelope identity collision")
                if prior is None:
                    self._write(self._envelope_path(envelope.envelope_id), _envelope_document(envelope))
                receipt_path = self._receipt_path(envelope.envelope_id)
                if not receipt_path.exists():
                    self._write(
                        receipt_path,
                        _receipt_document(DeliveryReceipt(
                            envelope_id=envelope.envelope_id,
                            envelope_digest=envelope.envelope_digest,
                            status=DeliveryStatus.PENDING,
                            attempt=0,
                        )),
                    )
                created.append(envelope)
        return tuple(created)


    def pending(self) -> tuple[MachineEnvelope, ...]:
        with self._lock, self._guard():
            result: list[MachineEnvelope] = []
            for path in sorted(self.envelopes.glob("*.json")):
                envelope = _decode_envelope(self._read(path))
                receipt = self._load_receipt(envelope)
                if receipt.status in {
                    DeliveryStatus.PENDING, DeliveryStatus.UNKNOWN, DeliveryStatus.FAILED,
                }:
                    result.append(envelope)
            return tuple(result)

    def mark(self, receipt: DeliveryReceipt) -> DeliveryReceipt:
        if not isinstance(receipt, DeliveryReceipt):
            raise TypeError("outbox accepts DeliveryReceipt")
        with self._lock, self._guard():
            envelope = self._load_envelope(receipt.envelope_id)
            if envelope is None:
                raise KeyError(receipt.envelope_id)
            if envelope.envelope_digest != receipt.envelope_digest:
                raise MachineConflict("delivery receipt envelope digest mismatch")
            current = self._load_receipt(envelope)
            if receipt.attempt < current.attempt:
                raise MachineConflict("delivery attempt cannot move backwards")
            if receipt.attempt == current.attempt and receipt != current:
                raise MachineConflict("delivery receipt conflict at same attempt")
            self._write(self._receipt_path(receipt.envelope_id), _receipt_document(receipt))
            return receipt

    def reconcile(self, commits: tuple[MachineCommit, ...]) -> tuple[MachineEnvelope, ...]:
        if type(commits) is not tuple or any(not isinstance(item, MachineCommit) for item in commits):
            raise TypeError("outbox reconcile expects typed commit tuple")
        result: list[MachineEnvelope] = []
        for commit in commits:
            result.extend(self.enqueue(commit))
        return tuple(result)


class DirectoryMachineInbox(_DirectoryDeliveryStore, MachineInboxPort):
    """Crash-durable receiver dedupe barrier."""

    def __init__(self, root: Path) -> None:
        super().__init__(Path(root) / "inbox")
        self.envelopes = self.root / "envelopes"
        self.envelopes.mkdir(exist_ok=True)

    def _path(self, envelope_id: str) -> Path:
        return self.envelopes / f"{envelope_id}.json"

    def accept(self, envelope: MachineEnvelope) -> bool:
        if not isinstance(envelope, MachineEnvelope):
            raise TypeError("inbox accepts MachineEnvelope")
        with self._lock, self._guard():
            prior_path = self._path(envelope.envelope_id)
            if prior_path.exists():
                prior = _decode_envelope(self._read(prior_path))
                if prior.envelope_digest != envelope.envelope_digest:
                    raise MachineConflict("inbox envelope identity collision")
                return False
            self._write(prior_path, _envelope_document(envelope))
            return True

    def contains(self, envelope_id: str) -> bool:
        if type(envelope_id) is not str or not envelope_id.strip():
            raise ValueError("inbox envelope_id is required")
        with self._lock:
            path = self._path(envelope_id)
            if not path.exists():
                return False
            _decode_envelope(self._read(path))
            return True


__all__ = [
    "DirectoryMachineInbox",
    "DirectoryMachineOutbox",
]