"""Stable Machine ABI shared by every Noetrium domain machine.

The kernel owns identity and accepted transitions. Domain interpreters own
meaning; providers and workers never become the source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from .canonical import canonical_digest, freeze_json, require_sha256
from .json_value import JsonObject, JsonValue
from .contracts import ChildMachineLink


class MachineKind(StrEnum):
    EXPERIMENT = "experiment"
    RUN = "run"
    METHOD = "method"
    AGENT = "agent"
    MEMORY = "memory"
    ENVIRONMENT = "environment"
    EVALUATION = "evaluation"


class MachineStatus(StrEnum):
    READY = "ready"
    RUNNABLE = "runnable"
    WAITING = "waiting"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class MachineError(RuntimeError):
    """Base error for Machine contract violations."""


class MachineConflict(MachineError):
    """A command was based on a stale machine revision."""


class MachineIntegrityError(MachineError):
    """A persisted machine fact failed integrity validation."""


@dataclass(frozen=True, slots=True)
class MachineIdentity:
    machine_id: str
    kind: MachineKind
    implementation_version: str
    generation_id: str

    def __post_init__(self) -> None:
        for value in (
            self.machine_id,
            self.implementation_version,
            self.generation_id,
        ):
            if type(value) is not str or not value.strip():
                raise ValueError("machine identity fields must be non-empty")
        if not isinstance(self.kind, MachineKind):
            raise TypeError("machine kind must be MachineKind")


@dataclass(frozen=True, slots=True)
class ProgramLock:
    """Complete execution lock for a portable program definition."""

    code_digest: str
    dependency_digest: str
    schema_digest: str
    interpreter_digest: str
    data_digest: str
    config_digest: str
    lock_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("code_digest", self.code_digest),
            ("dependency_digest", self.dependency_digest),
            ("schema_digest", self.schema_digest),
            ("interpreter_digest", self.interpreter_digest),
            ("data_digest", self.data_digest),
            ("config_digest", self.config_digest),
        ):
            require_sha256(value, f"program lock {name}")
        object.__setattr__(self, "lock_digest", canonical_digest({
            "code_digest": self.code_digest,
            "dependency_digest": self.dependency_digest,
            "schema_digest": self.schema_digest,
            "interpreter_digest": self.interpreter_digest,
            "data_digest": self.data_digest,
            "config_digest": self.config_digest,
        }))


@dataclass(frozen=True, slots=True)
class MachineProgramRef:
    program_digest: str
    schema_id: str
    program_kind: str
    program_version: str
    program_lock: ProgramLock

    def __post_init__(self) -> None:
        require_sha256(self.program_digest, "machine program_digest")
        if not isinstance(self.program_lock, ProgramLock):
            raise TypeError("machine program_lock must be ProgramLock")
        for value in (self.schema_id, self.program_kind, self.program_version):
            if type(value) is not str or not value.strip():
                raise ValueError("machine program fields must be non-empty")


@dataclass(frozen=True, slots=True)
class MachineCommand:
    command_id: str
    machine_id: str
    expected_revision: int
    kind: str
    payload: JsonValue = None
    scope: tuple[str, ...] = ()
    deadline_at: float | None = None
    parent_command_id: str | None = None
    idempotency_key: str | None = None
    payload_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for value in (self.command_id, self.machine_id, self.kind):
            if type(value) is not str or not value.strip():
                raise ValueError("machine command identity fields are required")
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            raise ValueError("machine command expected_revision must be non-negative")
        if type(self.scope) is not tuple or any(
            type(value) is not str or not value.strip() for value in self.scope
        ):
            raise TypeError("machine command scope must be non-empty text tuple")
        object.__setattr__(self, "payload", freeze_json(self.payload))
        object.__setattr__(
            self,
            "payload_digest",
            canonical_digest({
                "command_id": self.command_id,
                "machine_id": self.machine_id,
                "expected_revision": self.expected_revision,
                "kind": self.kind,
                "payload": self.payload,
                "scope": self.scope,
                "deadline_at": self.deadline_at,
                "parent_command_id": self.parent_command_id,
                "idempotency_key": self.idempotency_key,
            }),
        )


@dataclass(frozen=True, slots=True)
class TransitionProposal:
    machine_id: str
    command_id: str
    base_revision: int
    state_delta: JsonObject = field(default_factory=dict)
    emitted_commands: tuple[MachineCommand, ...] = ()
    output_refs: tuple[str, ...] = ()
    event_payloads: tuple[JsonValue, ...] = ()
    effect_intent_refs: tuple[str, ...] = ()
    wait_reason: str | None = None
    before_state_digest: str | None = None
    input_digest: str | None = None
    program_digest: str | None = None
    machine_kind: str | None = None
    machine_version: str | None = None
    input_refs: tuple[str, ...] = ()
    state_delta_ref: str | None = None
    evidence_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    parent_transition_id: str | None = None
    attempt_id: str | None = None
    authority_epoch: int | None = None
    child_links: tuple[ChildMachineLink, ...] = ()
    proposal_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for value in (self.machine_id, self.command_id):
            if type(value) is not str or not value.strip():
                raise ValueError("transition proposal identity fields are required")
        if type(self.base_revision) is not int or self.base_revision < 0:
            raise ValueError("transition proposal base_revision must be non-negative")
        if type(self.state_delta) is not dict and not hasattr(self.state_delta, "items"):
            raise TypeError("transition proposal state_delta must be a mapping")
        if type(self.emitted_commands) is not tuple or any(
            not isinstance(item, MachineCommand) for item in self.emitted_commands
        ):
            raise TypeError("transition proposal emitted_commands must be typed tuple")
        if type(self.child_links) is not tuple or any(
            not isinstance(item, ChildMachineLink) or item.parent_machine_id != self.machine_id
            for item in self.child_links
        ):
            raise TypeError("transition proposal child_links must belong to the parent machine")
        for name, values in ((
            ("output_refs", self.output_refs),
            ("input_refs", self.input_refs),
            ("evidence_refs", self.evidence_refs),
            ("artifact_refs", self.artifact_refs),
        )):
            if type(values) is not tuple or any(
                type(value) is not str or not value.strip() for value in values
            ):
                raise TypeError(f"transition proposal {name} must be non-empty text tuple")
        for name, value in ((
            ("before_state_digest", self.before_state_digest),
            ("input_digest", self.input_digest),
            ("program_digest", self.program_digest),
        )):
            if value is not None:
                require_sha256(value, f"transition proposal {name}")
        for name, value in ((
            ("machine_kind", self.machine_kind),
            ("machine_version", self.machine_version),
            ("state_delta_ref", self.state_delta_ref),
            ("parent_transition_id", self.parent_transition_id),
            ("attempt_id", self.attempt_id),
        )):
            if value is not None and (type(value) is not str or not value.strip()):
                raise ValueError(f"transition proposal {name} must be non-empty text")
        if self.authority_epoch is not None and (
            type(self.authority_epoch) is not int or self.authority_epoch < 0
        ):
            raise ValueError("transition proposal authority_epoch must be non-negative")
        if self.wait_reason is not None and (
            type(self.wait_reason) is not str or not self.wait_reason.strip()
        ):
            raise ValueError("transition proposal wait_reason must be non-empty")
        object.__setattr__(self, "state_delta", freeze_json(self.state_delta))
        object.__setattr__(
            self,
            "event_payloads",
            tuple(freeze_json(value) for value in self.event_payloads),
        )
        object.__setattr__(
            self,
            "proposal_digest",
            canonical_digest({
                "machine_id": self.machine_id,
                "command_id": self.command_id,
                "base_revision": self.base_revision,
                "state_delta": self.state_delta,
                "emitted_commands": self.emitted_commands,
                "output_refs": self.output_refs,
                "event_payloads": self.event_payloads,
                "effect_intent_refs": self.effect_intent_refs,
                "wait_reason": self.wait_reason,
                "before_state_digest": self.before_state_digest,
                "input_digest": self.input_digest,
                "program_digest": self.program_digest,
                "machine_kind": self.machine_kind,
                "machine_version": self.machine_version,
                "input_refs": self.input_refs,
                "state_delta_ref": self.state_delta_ref,
                "evidence_refs": self.evidence_refs,
                "artifact_refs": self.artifact_refs,
                "parent_transition_id": self.parent_transition_id,
                "attempt_id": self.attempt_id,
                "authority_epoch": self.authority_epoch,
                "child_links": self.child_links,
            }),
        )


@dataclass(frozen=True, slots=True)
class MachineCommit:
    machine_id: str
    command_id: str
    base_revision: int
    revision: int
    proposal_digest: str
    command_digest: str
    state: JsonObject = field(default_factory=dict)
    output_refs: tuple[str, ...] = ()
    event_payloads: tuple[JsonValue, ...] = ()
    effect_intent_refs: tuple[str, ...] = ()
    emitted_commands: tuple[MachineCommand, ...] = ()
    previous_commit_id: str | None = None
    before_state_digest: str | None = None
    input_digest: str | None = None
    program_digest: str | None = None
    machine_kind: str | None = None
    machine_version: str | None = None
    input_refs: tuple[str, ...] = ()
    state_delta_ref: str | None = None
    evidence_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    parent_transition_id: str | None = None
    attempt_id: str | None = None
    authority_epoch: int | None = None
    child_links: tuple[ChildMachineLink, ...] = ()
    state_digest: str = field(init=False)
    commit_id: str = field(init=False)

    def __post_init__(self) -> None:
        for value in (self.machine_id, self.command_id, self.proposal_digest):
            if type(value) is not str or not value.strip():
                raise ValueError("machine commit identity fields are required")
        require_sha256(self.proposal_digest, "machine commit proposal_digest")
        require_sha256(self.command_digest, "machine commit command_digest")
        if type(self.base_revision) is not int or self.base_revision < 0:
            raise ValueError("machine commit base_revision must be non-negative")
        if type(self.revision) is not int or self.revision != self.base_revision + 1:
            raise ValueError("machine commit revision must be base_revision + 1")
        if self.previous_commit_id is not None and (
            type(self.previous_commit_id) is not str or not self.previous_commit_id.strip()
        ):
            raise ValueError("machine commit previous_commit_id must be non-empty")
        if type(self.child_links) is not tuple or any(
            not isinstance(item, ChildMachineLink) or item.parent_machine_id != self.machine_id
            for item in self.child_links
        ):
            raise TypeError("machine commit child_links must belong to the parent machine")
        for name, values in ((
            ("output_refs", self.output_refs),
            ("input_refs", self.input_refs),
            ("evidence_refs", self.evidence_refs),
            ("artifact_refs", self.artifact_refs),
        )):
            if type(values) is not tuple or any(
                type(value) is not str or not value.strip() for value in values
            ):
                raise TypeError(f"machine commit {name} must be non-empty text tuple")
        for name, value in ((
            ("before_state_digest", self.before_state_digest),
            ("input_digest", self.input_digest),
            ("program_digest", self.program_digest),
        )):
            if value is not None:
                require_sha256(value, f"machine commit {name}")
        for name, value in ((
            ("machine_kind", self.machine_kind),
            ("machine_version", self.machine_version),
            ("state_delta_ref", self.state_delta_ref),
            ("parent_transition_id", self.parent_transition_id),
            ("attempt_id", self.attempt_id),
        )):
            if value is not None and (type(value) is not str or not value.strip()):
                raise ValueError(f"machine commit {name} must be non-empty text")
        if self.authority_epoch is not None and (
            type(self.authority_epoch) is not int or self.authority_epoch < 0
        ):
            raise ValueError("machine commit authority_epoch must be non-negative")
        object.__setattr__(self, "state", freeze_json(self.state))
        object.__setattr__(
            self,
            "event_payloads",
            tuple(freeze_json(value) for value in self.event_payloads),
        )
        object.__setattr__(self, "state_digest", canonical_digest(self.state))
        object.__setattr__(
            self,
            "commit_id",
            canonical_digest({
                "machine_id": self.machine_id,
                "command_id": self.command_id,
                "base_revision": self.base_revision,
                "revision": self.revision,
                "proposal_digest": self.proposal_digest,
                "command_digest": self.command_digest,
                "state": self.state,
                "output_refs": self.output_refs,
                "event_payloads": self.event_payloads,
                "effect_intent_refs": self.effect_intent_refs,
                "emitted_commands": self.emitted_commands,
                "previous_commit_id": self.previous_commit_id,
                "before_state_digest": self.before_state_digest,
                "input_digest": self.input_digest,
                "program_digest": self.program_digest,
                "machine_kind": self.machine_kind,
                "machine_version": self.machine_version,
                "input_refs": self.input_refs,
                "state_delta_ref": self.state_delta_ref,
                "evidence_refs": self.evidence_refs,
                "artifact_refs": self.artifact_refs,
                "parent_transition_id": self.parent_transition_id,
                "attempt_id": self.attempt_id,
                "authority_epoch": self.authority_epoch,
                "child_links": self.child_links,
            }),
        )


@dataclass(frozen=True, slots=True)
class MachineSnapshot:
    machine_id: str
    revision: int
    program: MachineProgramRef
    state: JsonObject
    parent_commit_id: str | None
    snapshot_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.machine_id) is not str or not self.machine_id.strip():
            raise ValueError("machine snapshot machine_id is required")
        if not isinstance(self.program, MachineProgramRef):
            raise TypeError("machine snapshot program must be MachineProgramRef")
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("machine snapshot revision must be non-negative")
        if self.parent_commit_id is not None and (
            type(self.parent_commit_id) is not str or not self.parent_commit_id.strip()
        ):
            raise ValueError("machine snapshot parent_commit_id must be non-empty")
        object.__setattr__(self, "state", freeze_json(self.state))
        object.__setattr__(
            self,
            "snapshot_id",
            canonical_digest({
                "machine_id": self.machine_id,
                "revision": self.revision,
                "program": self.program,
                "state": self.state,
                "parent_commit_id": self.parent_commit_id,
            }),
        )


@dataclass(frozen=True, slots=True)
class MachineInspection:
    identity: MachineIdentity
    program: MachineProgramRef
    status: MachineStatus
    revision: int
    state_digest: str
    pending_command_ids: tuple[str, ...] = ()
    last_commit_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, MachineStatus):
            raise TypeError("machine inspection status must be MachineStatus")
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("machine inspection revision must be non-negative")
        require_sha256(self.state_digest, "machine inspection state_digest")


@runtime_checkable
class MachinePort(Protocol):
    def open(self, program: MachineProgramRef, initial_state: JsonObject) -> MachineSnapshot: ...
    def step(self, command: MachineCommand, state: MachineSnapshot) -> TransitionProposal: ...
    def checkpoint(self, state: MachineSnapshot) -> MachineSnapshot: ...
    def restore(self, snapshot: MachineSnapshot) -> MachineSnapshot: ...
    def replay(self, journal: object) -> MachineSnapshot: ...
    def inspect(self, state: MachineSnapshot) -> MachineInspection: ...


__all__ = [
    "MachineCommand",
    "MachineConflict",
    "MachineError",
    "MachineIdentity",
    "MachineInspection",
    "MachineKind",
    "MachinePort",
    "MachineProgramRef",
    "ProgramLock",
    "MachineSnapshot",
    "MachineStatus",
    "MachineCommit",
    "MachineIntegrityError",
    "TransitionProposal",
]