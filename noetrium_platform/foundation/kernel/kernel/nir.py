"""Typed Noetrium Intermediate Representation command envelope."""

from __future__ import annotations

from dataclasses import dataclass, field

from .canonical import canonical_digest, freeze_json, require_sha256
from .json_value import JsonValue
from .machine import MachineCommand, MachineKind


@dataclass(frozen=True, slots=True)
class NIREnvelope:
    """Transport boundary; it is not a replacement for a domain program."""

    version: int
    machine_kind: MachineKind
    machine_id: str
    program_digest: str
    command_id: str
    command_kind: str
    expected_revision: int
    payload: JsonValue
    payload_digest: str
    parent_transition_id: str | None
    capability_scope: tuple[str, ...]
    deadline_at: float | None
    parent_command_id: str | None
    idempotency_key: str | None
    envelope_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version <= 0:
            raise ValueError("nir version must be positive")
        if not isinstance(self.machine_kind, MachineKind):
            raise TypeError("nir machine_kind must be MachineKind")
        for name, value in (
            ("machine_id", self.machine_id),
            ("command_id", self.command_id),
            ("command_kind", self.command_kind),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"nir {name} is required")
        require_sha256(self.program_digest, "nir program_digest")
        require_sha256(self.payload_digest, "nir payload_digest")
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            raise ValueError("nir expected_revision must be non-negative")
        if type(self.capability_scope) is not tuple or any(
            type(item) is not str or not item.strip() for item in self.capability_scope
        ):
            raise TypeError("nir capability_scope must be non-empty text tuple")
        object.__setattr__(self, "payload", freeze_json(self.payload))
        if canonical_digest({
            "command_id": self.command_id,
            "machine_id": self.machine_id,
            "expected_revision": self.expected_revision,
            "kind": self.command_kind,
            "payload": self.payload,
            "scope": self.capability_scope,
            "deadline_at": self.deadline_at,
            "parent_command_id": self.parent_command_id,
            "idempotency_key": self.idempotency_key,
        }) != self.payload_digest:
            raise ValueError("nir payload_digest does not match command identity")
        object.__setattr__(self, "envelope_digest", canonical_digest({
            "version": self.version,
            "machine_kind": self.machine_kind.value,
            "machine_id": self.machine_id,
            "program_digest": self.program_digest,
            "command_id": self.command_id,
            "command_kind": self.command_kind,
            "expected_revision": self.expected_revision,
            "payload": self.payload,
            "payload_digest": self.payload_digest,
            "parent_transition_id": self.parent_transition_id,
            "capability_scope": self.capability_scope,
            "deadline_at": self.deadline_at,
            "parent_command_id": self.parent_command_id,
            "idempotency_key": self.idempotency_key,
        }))


    @classmethod
    def from_command(
        cls,
        *,
        version: int,
        machine_kind: MachineKind,
        program_digest: str,
        command: MachineCommand,
        parent_transition_id: str | None = None,
    ) -> "NIREnvelope":
        if not isinstance(command, MachineCommand):
            raise TypeError("nir requires MachineCommand")
        return cls(
            version=version,
            machine_kind=machine_kind,
            machine_id=command.machine_id,
            program_digest=program_digest,
            command_id=command.command_id,
            command_kind=command.kind,
            expected_revision=command.expected_revision,
            payload=command.payload,
            payload_digest=command.payload_digest,
            parent_transition_id=parent_transition_id,
            capability_scope=command.scope,
            deadline_at=command.deadline_at,
            parent_command_id=command.parent_command_id,
            idempotency_key=command.idempotency_key,
        )

    def to_command(self) -> MachineCommand:
        return MachineCommand(
            command_id=self.command_id,
            machine_id=self.machine_id,
            expected_revision=self.expected_revision,
            kind=self.command_kind,
            payload=self.payload,
            scope=self.capability_scope,
            deadline_at=self.deadline_at,
            parent_command_id=self.parent_command_id,
            idempotency_key=self.idempotency_key,
        )


__all__ = ["NIREnvelope"]