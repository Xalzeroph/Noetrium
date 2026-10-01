"""Journal authorities for accepted Machine transitions.

The journal is the source of accepted facts. Workers only propose; a journal
accepts one monotonic revision per machine and rejects ambiguous duplicates.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
import re
from threading import RLock
from typing import Protocol, runtime_checkable

from .canonical import canonical_bytes, canonical_digest, require_sha256, strict_json_loads, thaw_json
from .durable_closure import (
    DurableCarrierReferenceClosure,
    durable_carrier_closure_complete,
    durable_carrier_gc_eligible,
    validate_durable_carrier_closures,
)
from .durability import (
    ChecksummedDocumentError,
    FilesystemCarrierGeneration,
    FilesystemCarrierKind,
    InterprocessFileLock,
    atomic_replace_bytes,
    capture_filesystem_carrier_generation,
    decode_checksummed_document,
    durable_append_bytes,
    durable_unlink,
    encode_checksummed_document,
    fsync_directory,
)
from .machine import (
    MachineCommand,
    MachineCommit,
    MachineConflict,
    MachineIntegrityError,
    MachineStatus,
)
from .contracts import ChildMachineLink


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


_MACHINE_COMMIT_RECORD_SCHEMA = "machine.commit.v3"
_DEFAULT_STATE_SNAPSHOT_INTERVAL = 256
_DEFAULT_STRUCTURED_STATE_THRESHOLD_BYTES = 0
_MACHINE_JOURNAL_RECOVERY_ANCHOR_SCHEMA = "machine.journal-recovery-anchor.v1"
_MACHINE_JOURNAL_RECOVERY_ANCHOR_FIELDS = {
    "machine_id", "prefix_size", "prefix_sha256", "anchor_commit",
    "has_emitted", "structured_state_enabled",
}
_JOURNAL_ID_TOKEN = re.compile(
    rb'"(command_id|commit_id)":("(?:\\\\.|[^"\\\\])*")'
)
_UNCHANGED = object()


def _state_patch(previous: object, current: object):
    if previous == current:
        return _UNCHANGED
    if isinstance(previous, Mapping) and isinstance(current, Mapping):
        changed: dict[str, object] = {}
        deleted = sorted(
            key
            for key in previous
            if key not in current
        )
        for key, value in current.items():
            if key not in previous:
                changed[str(key)] = {
                    "op": "replace",
                    "value": thaw_json(value),
                }
                continue
            patch = _state_patch(previous[key], value)
            if patch is not _UNCHANGED:
                changed[str(key)] = patch
        return {
            "op": "object",
            "set": changed,
            "delete": deleted,
        }
    if isinstance(previous, (tuple, list)) and isinstance(current, (tuple, list)):
        if (
            len(current) >= len(previous)
            and all(
                previous[index] == current[index]
                for index in range(len(previous))
            )
        ):
            return {
                "op": "append",
                "items": [
                    thaw_json(value)
                    for value in current[len(previous):]
                ],
            }
        if len(current) == len(previous):
            changed_items: list[list[object]] = []
            for index, value in enumerate(current):
                patch = _state_patch(previous[index], value)
                if patch is not _UNCHANGED:
                    changed_items.append([index, patch])
            return {
                "op": "array",
                "set": changed_items,
            }
    return {
        "op": "replace",
        "value": thaw_json(current),
    }


def _apply_state_patch(previous: object, patch: object) -> object:
    row = _require_object(patch, "journal state patch")
    operation = _require_text(row.get("op"), "journal state patch op")
    if operation == "replace":
        _require_exact(row, {"op", "value"}, "journal replace patch")
        return row["value"]
    if operation == "object":
        _require_exact(row, {"op", "set", "delete"}, "journal object patch")
        if not isinstance(previous, Mapping):
            raise MachineIntegrityError(
                "journal object patch requires mapping base"
            )
        changed = _require_object(row["set"], "journal object patch set")
        deleted = row["delete"]
        if not isinstance(deleted, list) or any(
            type(key) is not str for key in deleted
        ):
            raise MachineIntegrityError(
                "journal object patch delete must be a string list"
            )
        if deleted != sorted(set(deleted)):
            raise MachineIntegrityError(
                "journal object patch delete must be unique canonical order"
            )
        result = dict(previous)
        for key in deleted:
            if key not in result:
                raise MachineIntegrityError(
                    "journal object patch deletes absent key"
                )
            del result[key]
        for key, child_patch in changed.items():
            if key in previous:
                result[key] = _apply_state_patch(
                    previous[key],
                    child_patch,
                )
            else:
                child = _require_object(
                    child_patch,
                    "journal object insertion patch",
                )
                if set(child) != {"op", "value"} or child.get("op") != "replace":
                    raise MachineIntegrityError(
                        "journal object insertion requires replacement patch"
                    )
                result[key] = child["value"]
        return result
    if operation == "append":
        _require_exact(row, {"op", "items"}, "journal append patch")
        if not isinstance(previous, (tuple, list)):
            raise MachineIntegrityError(
                "journal append patch requires sequence base"
            )
        items = row["items"]
        if not isinstance(items, list):
            raise MachineIntegrityError(
                "journal append patch items must be a list"
            )
        return [*previous, *items]
    if operation == "array":
        _require_exact(row, {"op", "set"}, "journal array patch")
        if not isinstance(previous, (tuple, list)):
            raise MachineIntegrityError(
                "journal array patch requires sequence base"
            )
        changes = row["set"]
        if not isinstance(changes, list):
            raise MachineIntegrityError(
                "journal array patch set must be a list"
            )
        result = list(previous)
        previous_index = -1
        for entry in changes:
            if (
                not isinstance(entry, list)
                or len(entry) != 2
                or type(entry[0]) is not int
            ):
                raise MachineIntegrityError(
                    "journal array patch entry must be [index, patch]"
                )
            index = entry[0]
            if (
                index < 0
                or index >= len(result)
                or index <= previous_index
            ):
                raise MachineIntegrityError(
                    "journal array patch indexes must be unique canonical order"
                )
            previous_index = index
            result[index] = _apply_state_patch(
                previous[index],
                entry[1],
            )
        return result
    if operation == "same":
        _require_exact(row, {"op"}, "journal same patch")
        return previous
    raise MachineIntegrityError(
        f"unknown journal state patch operation: {operation}"
    )


def _state_record(
    commit: MachineCommit,
    previous_state: object | None,
    *,
    force_snapshot: bool,
) -> tuple[str, object]:
    if previous_state is None or force_snapshot:
        return "snapshot", thaw_json(commit.state)
    patch = _state_patch(previous_state, commit.state)
    return "patch", ({"op": "same"} if patch is _UNCHANGED else patch)


def _commit_document(
    commit: MachineCommit,
    *,
    previous_state: object | None,
    force_snapshot: bool,
) -> dict[str, object]:
    state_encoding, state_payload = _state_record(
        commit,
        previous_state,
        force_snapshot=force_snapshot,
    )
    return {
        "record_schema": _MACHINE_COMMIT_RECORD_SCHEMA,
        "commit_id": commit.commit_id,
        "machine_id": commit.machine_id,
        "command_id": commit.command_id,
        "base_revision": commit.base_revision,
        "revision": commit.revision,
        "proposal_digest": commit.proposal_digest,
        "command_digest": commit.command_digest,
        "state_encoding": state_encoding,
        "state_payload": state_payload,
        "resulting_state_digest": commit.state_digest,
        "output_refs": list(commit.output_refs),
        "event_payloads": [thaw_json(value) for value in commit.event_payloads],
        "effect_intent_refs": list(commit.effect_intent_refs),
        "emitted_commands": [_command_document(value) for value in commit.emitted_commands],
        "previous_commit_id": commit.previous_commit_id,
        "before_state_digest": commit.before_state_digest,
        "input_digest": commit.input_digest,
        "program_digest": commit.program_digest,
        "program_lock_digest": commit.program_lock_digest,
        "machine_kind": commit.machine_kind,
        "machine_version": commit.machine_version,
        "input_refs": list(commit.input_refs),
        "state_delta_ref": commit.state_delta_ref,
        "evidence_refs": list(commit.evidence_refs),
        "artifact_refs": list(commit.artifact_refs),
        "parent_transition_id": commit.parent_transition_id,
        "attempt_id": commit.attempt_id,
        "authority_epoch": commit.authority_epoch,
        "child_links": [value.as_dict() for value in commit.child_links],
        "accepted_status": commit.accepted_status.value,
    }


def _require_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise MachineIntegrityError(f"{label} must be an object")
    return value


def _require_exact(row: dict[str, object], fields: set[str], label: str) -> None:
    if set(row) != fields:
        raise MachineIntegrityError(f"{label} fields are not exact")


def _require_text(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise MachineIntegrityError(f"{label} must be non-empty text")
    return value


def _require_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise MachineIntegrityError(f"{label} must be a non-negative integer")
    return value


def _decode_command(value: object) -> MachineCommand:
    row = _require_object(value, "journal command")
    _require_exact(row, {
        "command_id", "machine_id", "expected_revision", "kind", "payload",
        "scope", "deadline_at", "parent_command_id", "idempotency_key",
        "payload_digest",
    }, "journal command")
    scope = row["scope"]
    if not isinstance(scope, list):
        raise MachineIntegrityError("journal command scope must be a list")
    command = MachineCommand(
        command_id=_require_text(row["command_id"], "command_id"),
        machine_id=_require_text(row["machine_id"], "machine_id"),
        expected_revision=_require_int(row["expected_revision"], "expected_revision"),
        kind=_require_text(row["kind"], "command kind"),
        payload=row["payload"],  # type: ignore[arg-type]
        scope=tuple(_require_text(value, "scope item") for value in scope),
        deadline_at=row["deadline_at"],  # type: ignore[arg-type]
        parent_command_id=row["parent_command_id"],  # type: ignore[arg-type]
        idempotency_key=row["idempotency_key"],  # type: ignore[arg-type]
    )
    if command.payload_digest != _require_text(row["payload_digest"], "payload_digest"):
        raise MachineIntegrityError("journal command payload digest mismatch")
    return command


def _decode_child_link(value: object) -> ChildMachineLink:
    row = _require_object(value, "journal child link")
    _require_exact(row, {
        "parent_machine_id", "child_machine_id", "child_program_digest",
        "child_program_lock_digest", "child_snapshot_ref", "child_transition_start", "child_transition_end",
        "child_result_ref", "failure_policy", "link_digest",
    }, "journal child link")
    link = ChildMachineLink(
        parent_machine_id=_require_text(row["parent_machine_id"], "parent_machine_id"),
        child_machine_id=_require_text(row["child_machine_id"], "child_machine_id"),
        child_program_digest=_require_text(row["child_program_digest"], "child_program_digest"),
        child_program_lock_digest=_require_text(
            row["child_program_lock_digest"],
            "child_program_lock_digest",
        ),
        child_snapshot_ref=_require_text(row["child_snapshot_ref"], "child_snapshot_ref"),
        child_transition_start=_require_int(row["child_transition_start"], "child_transition_start"),
        child_transition_end=_require_int(row["child_transition_end"], "child_transition_end"),
        child_result_ref=row["child_result_ref"],  # type: ignore[arg-type]
        failure_policy=_require_text(row["failure_policy"], "failure_policy"),
    )
    if link.link_digest != _require_text(row["link_digest"], "link_digest"):
        raise MachineIntegrityError("journal child link digest mismatch")
    return link


def _decode_commit(
    value: object,
    *,
    previous_state: object | None,
) -> MachineCommit:
    row = _require_object(value, "journal commit")
    _require_exact(row, {
        "record_schema", "commit_id", "machine_id", "command_id", "base_revision", "revision",
        "proposal_digest", "command_digest", "state_encoding", "state_payload",
        "resulting_state_digest", "output_refs", "event_payloads",
        "effect_intent_refs", "emitted_commands", "previous_commit_id", "before_state_digest",
        "input_digest", "program_digest", "program_lock_digest", "machine_kind", "machine_version", "input_refs",
        "state_delta_ref", "evidence_refs", "artifact_refs", "parent_transition_id", "attempt_id",
        "authority_epoch", "child_links", "accepted_status",
    }, "journal commit")
    if row["record_schema"] != _MACHINE_COMMIT_RECORD_SCHEMA:
        raise MachineIntegrityError(
            "machine journal commit schema is not current"
        )
    encoding = _require_text(
        row["state_encoding"],
        "journal state encoding",
    )
    payload = row["state_payload"]
    if encoding == "snapshot":
        state = _require_object(
            payload,
            "journal snapshot state",
        )
    elif encoding == "patch":
        if previous_state is None:
            raise MachineIntegrityError(
                "journal patch state requires a previous committed state"
            )
        state = _apply_state_patch(previous_state, payload)
    else:
        raise MachineIntegrityError(
            f"unknown journal state encoding: {encoding}"
        )
    resulting_state_digest = _require_text(
        row["resulting_state_digest"],
        "journal resulting state digest",
    )
    require_sha256(
        resulting_state_digest,
        "journal resulting state digest",
    )
    if canonical_digest(state) != resulting_state_digest:
        raise MachineIntegrityError(
            "journal resulting state digest mismatch"
        )
    if previous_state is not None and row["before_state_digest"] is not None:
        if canonical_digest(previous_state) != row["before_state_digest"]:
            raise MachineIntegrityError(
                "journal before_state_digest mismatch"
            )

    output_refs = row["output_refs"]
    effect_refs = row["effect_intent_refs"]
    input_refs = row["input_refs"]
    evidence_refs = row["evidence_refs"]
    artifact_refs = row["artifact_refs"]
    child_links = row["child_links"]
    events = row["event_payloads"]
    commands = row["emitted_commands"]
    if not all(isinstance(item, list) for item in (
        output_refs, effect_refs, input_refs, evidence_refs, artifact_refs, child_links, events, commands
    )):
        raise MachineIntegrityError("journal commit collection fields must be lists")
    commit = MachineCommit(
        machine_id=_require_text(row["machine_id"], "machine_id"),
        command_id=_require_text(row["command_id"], "command_id"),
        base_revision=_require_int(row["base_revision"], "base_revision"),
        revision=_require_int(row["revision"], "revision"),
        proposal_digest=_require_text(row["proposal_digest"], "proposal_digest"),
        command_digest=_require_text(row["command_digest"], "command_digest"),
        state=state,  # type: ignore[arg-type]
        output_refs=tuple(_require_text(item, "output ref") for item in output_refs),
        event_payloads=tuple(events),  # type: ignore[arg-type]
        effect_intent_refs=tuple(_require_text(item, "effect ref") for item in effect_refs),
        emitted_commands=tuple(_decode_command(item) for item in commands),
        previous_commit_id=row["previous_commit_id"],  # type: ignore[arg-type]
        before_state_digest=row["before_state_digest"],  # type: ignore[arg-type]
        input_digest=row["input_digest"],  # type: ignore[arg-type]
        program_digest=_require_text(row["program_digest"], "program_digest"),
        program_lock_digest=_require_text(
            row["program_lock_digest"],
            "program_lock_digest",
        ),
        machine_kind=row["machine_kind"],  # type: ignore[arg-type]
        machine_version=row["machine_version"],  # type: ignore[arg-type]
        input_refs=tuple(_require_text(item, "input ref") for item in input_refs),
        state_delta_ref=row["state_delta_ref"],  # type: ignore[arg-type]
        evidence_refs=tuple(_require_text(item, "evidence ref") for item in evidence_refs),
        artifact_refs=tuple(_require_text(item, "artifact ref") for item in artifact_refs),
        parent_transition_id=row["parent_transition_id"],  # type: ignore[arg-type]
        attempt_id=row["attempt_id"],  # type: ignore[arg-type]
        authority_epoch=row["authority_epoch"],  # type: ignore[arg-type]
        child_links=tuple(_decode_child_link(item) for item in child_links),
        accepted_status=MachineStatus(_require_text(row["accepted_status"], "accepted_status")),
    )
    if commit.state_digest != resulting_state_digest:
        raise MachineIntegrityError(
            "journal reconstructed commit state digest mismatch"
        )
    stored_commit_id = _require_text(
        row["commit_id"],
        "journal commit_id",
    )
    require_sha256(stored_commit_id, "journal commit_id")
    if commit.commit_id != stored_commit_id:
        raise MachineIntegrityError(
            "journal commit identity digest mismatch"
        )
    return commit



_MACHINE_JOURNAL_RETIREMENT_SCHEMA = "machine.journal-retirement.v2"
_MACHINE_JOURNAL_RETIREMENT_FIELDS = {
    "machine_id",
    "terminal_commit_id",
    "terminal_revision",
    "content_sha256",
    "byte_size",
    "gc_proof_digest",
    "carrier_generation",
    "phase",
}


class MachineJournalRetirementPhase(StrEnum):
    RETIRED = "retired"
    QUARANTINED = "quarantined"
    PURGED = "purged"


@dataclass(frozen=True, slots=True)
class MachineJournalGcAssessment:
    """Exact fail-closed GC cut for one durable Machine Journal generation."""

    machine_id: str
    terminal_commit_id: str
    terminal_revision: int
    content_sha256: str
    byte_size: int
    closures: tuple[DurableCarrierReferenceClosure, ...] = ()
    proof_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            type(self.machine_id) is not str
            or not self.machine_id.strip()
            or self.machine_id != self.machine_id.strip()
        ):
            raise ValueError("machine journal GC machine_id must be canonical text")
        require_sha256(
            self.terminal_commit_id,
            "machine journal GC terminal_commit_id",
        )
        if (
            type(self.terminal_revision) is not int
            or self.terminal_revision <= 0
        ):
            raise ValueError(
                "machine journal GC terminal_revision must be positive"
            )
        require_sha256(
            self.content_sha256,
            "machine journal GC content_sha256",
        )
        if type(self.byte_size) is not int or self.byte_size <= 0:
            raise ValueError("machine journal GC byte_size must be positive")
        validate_durable_carrier_closures(self.closures)
        object.__setattr__(
            self,
            "proof_digest",
            canonical_digest(
                {
                    "schema": "machine.journal-gc-assessment.v1",
                    "machine_id": self.machine_id,
                    "terminal_commit_id": self.terminal_commit_id,
                    "terminal_revision": self.terminal_revision,
                    "content_sha256": self.content_sha256,
                    "byte_size": self.byte_size,
                    "closures": [
                        {
                            "authority": closure.authority.value,
                            "proof_digest": closure.proof_digest,
                            "retained_reference_ids": list(
                                closure.retained_reference_ids
                            ),
                        }
                        for closure in self.closures
                    ],
                }
            ),
        )

    @property
    def closure_complete(self) -> bool:
        return durable_carrier_closure_complete(self.closures)

    @property
    def eligible(self) -> bool:
        return durable_carrier_gc_eligible(self.closures)


@runtime_checkable
class MachineJournalGcPort(Protocol):
    def assess_gc(
        self,
        machine_id: str,
        *,
        closures: tuple[DurableCarrierReferenceClosure, ...] = (),
    ) -> MachineJournalGcAssessment: ...

    def purge(
        self,
        machine_id: str,
        *,
        gc: MachineJournalGcAssessment,
    ) -> bool: ...


@runtime_checkable
class MachineJournalPort(Protocol):
    def append(self, commit: MachineCommit) -> MachineCommit: ...
    def head(
        self,
        machine_id: str,
    ) -> tuple[MachineCommit | None, bool]: ...
    def latest(self, machine_id: str) -> MachineCommit | None: ...
    def get(self, commit_id: str) -> MachineCommit | None: ...
    def command_commit(
        self,
        machine_id: str,
        command_id: str,
    ) -> MachineCommit | None: ...
    def has_emitted_commands(self, machine_id: str) -> bool: ...
    def commits(self, machine_id: str) -> tuple[MachineCommit, ...]: ...


class _JournalHistory:
    """Validated in-process projection of one append-only Machine journal."""

    __slots__ = ("commits", "by_command_id", "by_commit_id", "has_emitted")

    def __init__(
        self,
        commits: list[MachineCommit] | None = None,
    ) -> None:
        self.commits: list[MachineCommit] = []
        self.by_command_id: dict[str, MachineCommit] = {}
        self.by_commit_id: dict[str, MachineCommit] = {}
        self.has_emitted = False
        for commit in commits or ():
            self.accept(commit)

    def clone(self) -> "_JournalHistory":
        value = _JournalHistory()
        value.commits = list(self.commits)
        value.by_command_id = dict(self.by_command_id)
        value.by_commit_id = dict(self.by_commit_id)
        value.has_emitted = self.has_emitted
        return value

    def validate_next(
        self,
        commit: MachineCommit,
    ) -> MachineCommit | None:
        existing = self.by_command_id.get(commit.command_id)
        if existing is not None:
            if existing == commit:
                return existing
            raise MachineConflict(
                "command_id already committed with different payload: "
                f"{commit.command_id}"
            )
        existing = self.by_commit_id.get(commit.commit_id)
        if existing is not None:
            return existing
        latest = self.commits[-1] if self.commits else None
        expected_base = 0 if latest is None else latest.revision
        if commit.base_revision != expected_base:
            raise MachineConflict(
                "stale machine revision: "
                f"expected={expected_base} actual={commit.base_revision}"
            )
        expected_previous = None if latest is None else latest.commit_id
        if commit.previous_commit_id != expected_previous:
            raise MachineConflict(
                "machine commit previous_commit_id does not match journal head"
            )
        if latest is not None and (
            commit.program_digest != latest.program_digest
            or commit.program_lock_digest != latest.program_lock_digest
        ):
            raise MachineConflict(
                "machine commit executable identity does not match journal head"
            )
        return None

    def accept(self, commit: MachineCommit) -> MachineCommit:
        existing = self.validate_next(commit)
        if existing is not None:
            return existing
        self.commits.append(commit)
        self.by_command_id[commit.command_id] = commit
        self.by_commit_id[commit.commit_id] = commit
        if commit.emitted_commands:
            self.has_emitted = True
        return commit

    def snapshot(self) -> tuple[MachineCommit, ...]:
        return tuple(self.commits)




class InMemoryMachineJournal(MachineJournalPort):
    """Thread-safe journal authority for tests and embedded execution."""

    durability = "process_local"

    def __init__(self) -> None:
        self._histories: dict[str, _JournalHistory] = {}
        self._by_id: dict[str, MachineCommit] = {}
        self._lock = RLock()

    def _history_for(self, machine_id: str) -> _JournalHistory:
        history = self._histories.get(machine_id)
        if history is None:
            history = _JournalHistory()
            self._histories[machine_id] = history
        return history

    def append(self, commit: MachineCommit) -> MachineCommit:
        if not isinstance(commit, MachineCommit):
            raise TypeError("machine journal accepts MachineCommit")
        with self._lock:
            accepted = self._history_for(commit.machine_id).accept(commit)
            self._by_id[accepted.commit_id] = accepted
            return accepted

    def head(
        self,
        machine_id: str,
    ) -> tuple[MachineCommit | None, bool]:
        if type(machine_id) is not str or not machine_id.strip():
            raise ValueError("machine_id is required")
        with self._lock:
            history = self._histories.get(machine_id)
            if history is None:
                return None, False
            latest = None if not history.commits else history.commits[-1]
            return latest, history.has_emitted

    def latest(self, machine_id: str) -> MachineCommit | None:
        return self.head(machine_id)[0]

    def get(self, commit_id: str) -> MachineCommit | None:
        with self._lock:
            return self._by_id.get(commit_id)

    def command_commit(
        self,
        machine_id: str,
        command_id: str,
    ) -> MachineCommit | None:
        if type(machine_id) is not str or not machine_id.strip():
            raise ValueError("machine_id is required")
        if type(command_id) is not str or not command_id.strip():
            raise ValueError("command_id is required")
        with self._lock:
            history = self._histories.get(machine_id)
            return (
                None
                if history is None
                else history.by_command_id.get(command_id)
            )

    def has_emitted_commands(self, machine_id: str) -> bool:
        if type(machine_id) is not str or not machine_id.strip():
            raise ValueError("machine_id is required")
        with self._lock:
            history = self._histories.get(machine_id)
            return False if history is None else history.has_emitted

    def commits(self, machine_id: str) -> tuple[MachineCommit, ...]:
        with self._lock:
            history = self._histories.get(machine_id)
            return () if history is None else history.snapshot()


class _DirectoryJournalCache:
    __slots__ = (
        "history",
        "file_identity",
        "structured_state_enabled",
        "history_complete",
        "prefix_command_tokens",
        "prefix_commit_tokens",
        "prefix_hasher",
        "prefix_size",
    )

    def __init__(
        self,
        history: _JournalHistory,
        file_identity: tuple[int, int, int, int, int] | None,
        structured_state_enabled: bool = False,
        *,
        history_complete: bool = True,
        prefix_command_tokens: frozenset[bytes] = frozenset(),
        prefix_commit_tokens: frozenset[bytes] = frozenset(),
        prefix_hasher=None,
        prefix_size: int = 0,
    ) -> None:
        self.history = history
        self.file_identity = file_identity
        self.structured_state_enabled = structured_state_enabled
        self.history_complete = history_complete
        self.prefix_command_tokens = prefix_command_tokens
        self.prefix_commit_tokens = prefix_commit_tokens
        self.prefix_hasher = sha256() if prefix_hasher is None else prefix_hasher
        self.prefix_size = prefix_size


class DirectoryMachineJournal(MachineJournalPort, MachineJournalGcPort):
    """Crash-durable append-only journal with derived incremental acceleration.

    The journal file remains the sole authority. The in-process cache is
    discarded and rebuilt from the complete canonical file whenever another
    writer changes that file. Repeated appends by the same authority therefore
    avoid O(history) rescans without introducing a sidecar truth source.
    """

    durability = "crash_durable"

    def __init__(
        self,
        root: Path,
        *,
        structured_state_threshold_bytes: int = (
            _DEFAULT_STRUCTURED_STATE_THRESHOLD_BYTES
        ),
        state_snapshot_interval: int = _DEFAULT_STATE_SNAPSHOT_INTERVAL,
    ) -> None:
        if (
            type(structured_state_threshold_bytes) is not int
            or structured_state_threshold_bytes < 0
        ):
            raise ValueError(
                "structured_state_threshold_bytes must be non-negative integer"
            )
        if (
            type(state_snapshot_interval) is not int
            or state_snapshot_interval < 1
        ):
            raise ValueError(
                "state_snapshot_interval must be positive integer"
            )
        self.root = Path(root)
        self.logs = self.root / "machines"
        self.locks = self.root / "locks"
        self.anchors = self.root / "recovery-anchors"
        self.logs.mkdir(parents=True, exist_ok=True)
        self.locks.mkdir(parents=True, exist_ok=True)
        self.anchors.mkdir(parents=True, exist_ok=True)
        self._structured_state_threshold_bytes = (
            structured_state_threshold_bytes
        )
        self._state_snapshot_interval = state_snapshot_interval
        self._cache: dict[str, _DirectoryJournalCache] = {}
        self._cache_lock = RLock()

    @staticmethod
    def _file_key(machine_id: str) -> str:
        from hashlib import sha256
        return sha256(machine_id.encode("utf-8")).hexdigest()

    def _log_path(self, machine_id: str) -> Path:
        return self.logs / f"{self._file_key(machine_id)}.journal"

    def _lock_path(self, machine_id: str) -> Path:
        return self.locks / f"{self._file_key(machine_id)}.lock"

    def _anchor_path(self, machine_id: str) -> Path:
        return self.anchors / f"{self._file_key(machine_id)}.json"

    def _retirement_path(self, machine_id: str) -> Path:
        return (
            self.logs
            / ".retired"
            / f"{self._file_key(machine_id)}.json"
        )

    def _quarantine_path(self, machine_id: str) -> Path:
        return (
            self.logs
            / ".retired-journals"
            / f"{self._file_key(machine_id)}.journal"
        )

    def _load_retirement(
        self,
        machine_id: str,
    ) -> dict[str, object] | None:
        path = self._retirement_path(machine_id)
        if not path.exists():
            return None
        try:
            payload = decode_checksummed_document(
                path.read_bytes(),
                expected_schema=_MACHINE_JOURNAL_RETIREMENT_SCHEMA,
            ).payload
        except (OSError, ChecksummedDocumentError) as exc:
            raise MachineIntegrityError(
                "machine journal retirement intent is corrupt"
            ) from exc
        if set(payload) != _MACHINE_JOURNAL_RETIREMENT_FIELDS:
            raise MachineIntegrityError(
                "machine journal retirement fields are not exact"
            )
        if payload.get("machine_id") != machine_id:
            raise MachineIntegrityError(
                "machine journal retirement identity mismatch"
            )
        try:
            require_sha256(
                str(payload["terminal_commit_id"]),
                "machine journal retirement terminal_commit_id",
            )
            require_sha256(
                str(payload["content_sha256"]),
                "machine journal retirement content_sha256",
            )
            require_sha256(
                str(payload["gc_proof_digest"]),
                "machine journal retirement gc_proof_digest",
            )
            phase = MachineJournalRetirementPhase(str(payload["phase"]))
            terminal_revision = payload["terminal_revision"]
            byte_size = payload["byte_size"]
            carrier_generation = FilesystemCarrierGeneration.from_data(
                payload["carrier_generation"]
            )
            if carrier_generation.kind is not FilesystemCarrierKind.REGULAR_FILE:
                raise ValueError(
                    "machine journal carrier generation must be a regular file"
                )
            if (
                type(terminal_revision) is not int
                or terminal_revision <= 0
                or type(byte_size) is not int
                or byte_size <= 0
            ):
                raise ValueError("invalid numeric retirement identity")
        except (KeyError, TypeError, ValueError) as exc:
            raise MachineIntegrityError(
                "machine journal retirement intent is invalid"
            ) from exc
        return {
            "machine_id": machine_id,
            "terminal_commit_id": str(payload["terminal_commit_id"]),
            "terminal_revision": terminal_revision,
            "content_sha256": str(payload["content_sha256"]),
            "byte_size": byte_size,
            "gc_proof_digest": str(payload["gc_proof_digest"]),
            "carrier_generation": carrier_generation,
            "phase": phase,
        }

    def _publish_retirement(
        self,
        gc: MachineJournalGcAssessment,
        phase: MachineJournalRetirementPhase,
        *,
        carrier_generation: FilesystemCarrierGeneration,
    ) -> None:
        if carrier_generation.kind is not FilesystemCarrierKind.REGULAR_FILE:
            raise TypeError(
                "machine journal retirement carrier must be a regular file"
            )
        atomic_replace_bytes(
            self._retirement_path(gc.machine_id),
            encode_checksummed_document(
                _MACHINE_JOURNAL_RETIREMENT_SCHEMA,
                {
                    "machine_id": gc.machine_id,
                    "terminal_commit_id": gc.terminal_commit_id,
                    "terminal_revision": gc.terminal_revision,
                    "content_sha256": gc.content_sha256,
                    "byte_size": gc.byte_size,
                    "gc_proof_digest": gc.proof_digest,
                    "carrier_generation": carrier_generation.to_data(),
                    "phase": phase.value,
                },
            ),
        )

    def _gc_identity_locked(
        self,
        machine_id: str,
    ) -> tuple[str, int, str, int]:
        path = self._log_path(machine_id)
        before = self._file_identity(path)
        if before is None:
            raise KeyError(f"machine journal does not exist: {machine_id}")
        cache = self._read_authoritative(machine_id)
        if not cache.history.commits:
            raise MachineIntegrityError(
                "machine journal GC requires at least one accepted commit"
            )
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise MachineIntegrityError(
                f"cannot read machine journal for GC: {path}"
            ) from exc
        after = self._file_identity(path)
        if after != before or cache.file_identity != after:
            raise MachineIntegrityError(
                "machine journal changed during GC identity capture"
            )
        latest = cache.history.commits[-1]
        return (
            latest.commit_id,
            latest.revision,
            sha256(raw).hexdigest(),
            len(raw),
        )

    @staticmethod
    def _require_gc_identity(
        gc: MachineJournalGcAssessment,
        current: tuple[str, int, str, int],
    ) -> None:
        if current != (
            gc.terminal_commit_id,
            gc.terminal_revision,
            gc.content_sha256,
            gc.byte_size,
        ):
            raise RuntimeError(
                "machine journal changed after GC assessment"
            )

    @staticmethod
    def _file_identity(
        path: Path,
    ) -> tuple[int, int, int, int, int] | None:
        try:
            stat = path.stat()
        except FileNotFoundError:
            return None
        return (
            int(stat.st_size),
            int(stat.st_mtime_ns),
            int(stat.st_ctime_ns),
            int(stat.st_dev),
            int(stat.st_ino),
        )

    @staticmethod
    def _decode_line(
        line: bytes,
        *,
        machine_id: str,
        path: Path,
        previous_state: object | None,
    ) -> MachineCommit:
        try:
            document = strict_json_loads(line)
            commit = _decode_commit(
                document,
                previous_state=previous_state,
            )
            if commit.machine_id != machine_id:
                raise MachineIntegrityError(
                    "journal machine identity mismatch"
                )
            if canonical_bytes(document) != line:
                raise MachineIntegrityError(
                    "journal line is not canonical JSON"
                )
            return commit
        except MachineIntegrityError:
            raise
        except (TypeError, ValueError) as exc:
            raise MachineIntegrityError(
                f"cannot decode machine journal: {path}"
            ) from exc

    @staticmethod
    def _seed_history_from_anchor(
        anchor: MachineCommit,
        *,
        has_emitted: bool,
    ) -> _JournalHistory:
        history = _JournalHistory()
        history.commits.append(anchor)
        history.by_command_id[anchor.command_id] = anchor
        history.by_commit_id[anchor.commit_id] = anchor
        history.has_emitted = bool(has_emitted or anchor.emitted_commands)
        return history

    def _load_recovery_anchor(
        self,
        machine_id: str,
        *,
        raw: bytes,
        path: Path,
        file_identity: tuple[int, int, int, int, int],
    ) -> _DirectoryJournalCache | None:
        anchor_path = self._anchor_path(machine_id)
        if not anchor_path.is_file():
            return None
        try:
            payload = decode_checksummed_document(
                anchor_path.read_bytes(),
                expected_schema=_MACHINE_JOURNAL_RECOVERY_ANCHOR_SCHEMA,
            ).payload
            if set(payload) != _MACHINE_JOURNAL_RECOVERY_ANCHOR_FIELDS:
                return None
            if payload.get("machine_id") != machine_id:
                return None
            prefix_size = payload.get("prefix_size")
            prefix_sha256 = payload.get("prefix_sha256")
            has_emitted = payload.get("has_emitted")
            structured_state_enabled = payload.get("structured_state_enabled")
            anchor_document = payload.get("anchor_commit")
            if (
                type(prefix_size) is not int
                or prefix_size <= 0
                or prefix_size > len(raw)
                or type(prefix_sha256) is not str
                or type(has_emitted) is not bool
                or type(structured_state_enabled) is not bool
                or not isinstance(anchor_document, dict)
            ):
                return None
            require_sha256(
                prefix_sha256,
                "machine journal recovery anchor prefix_sha256",
            )
            prefix = raw[:prefix_size]
            prefix_hasher = sha256()
            prefix_hasher.update(prefix)
            if prefix_hasher.hexdigest() != prefix_sha256:
                return None
            if anchor_document.get("state_encoding") != "snapshot":
                return None
            anchor_line = canonical_bytes(anchor_document) + b"\n"
            if len(anchor_line) > prefix_size or not prefix.endswith(anchor_line):
                return None
            anchor = _decode_commit(
                anchor_document,
                previous_state=None,
            )
            if (
                anchor.machine_id != machine_id
                or anchor.revision <= 0
                or anchor.revision % self._state_snapshot_interval != 0
            ):
                return None

            prefix_before_anchor = prefix[:-len(anchor_line)]
            command_tokens: set[bytes] = set()
            commit_tokens: set[bytes] = set()
            for match in _JOURNAL_ID_TOKEN.finditer(prefix_before_anchor):
                if match.group(1) == b"command_id":
                    command_tokens.add(match.group(2))
                else:
                    commit_tokens.add(match.group(2))
            prefix_command_tokens = frozenset(command_tokens)
            prefix_commit_tokens = frozenset(commit_tokens)
            history = self._seed_history_from_anchor(
                anchor,
                has_emitted=has_emitted,
            )
            previous_state: object | None = anchor.state
            tail = raw[prefix_size:]
            prefix_hasher.update(tail)
            for line in tail.splitlines():
                if not line:
                    continue
                if len(line) > self._structured_state_threshold_bytes:
                    structured_state_enabled = True
                commit = self._decode_line(
                    line,
                    machine_id=machine_id,
                    path=path,
                    previous_state=previous_state,
                )
                history.accept(commit)
                previous_state = commit.state
            return _DirectoryJournalCache(
                history,
                file_identity,
                structured_state_enabled,
                history_complete=False,
                prefix_command_tokens=prefix_command_tokens,
                prefix_commit_tokens=prefix_commit_tokens,
                prefix_hasher=prefix_hasher,
                prefix_size=len(raw),
            )
        except (
            OSError,
            ChecksummedDocumentError,
            MachineIntegrityError,
            MachineConflict,
            TypeError,
            ValueError,
        ):
            # Recovery anchors are disposable acceleration artifacts. Any
            # malformed/stale anchor falls back to full authoritative replay.
            return None

    def _publish_recovery_anchor(
        self,
        commit: MachineCommit,
        *,
        committed_payload: bytes,
        prefix_size: int,
        prefix_sha256: str,
        has_emitted: bool,
        structured_state_enabled: bool,
    ) -> None:
        if commit.revision % self._state_snapshot_interval != 0:
            return
        try:
            anchor_document = _commit_document(
                commit,
                previous_state=None,
                force_snapshot=True,
            )
            anchor_line = canonical_bytes(anchor_document) + b"\n"
            if committed_payload != anchor_line:
                raise MachineIntegrityError(
                    "recovery anchor revision was not committed as full snapshot"
                )
            require_sha256(
                prefix_sha256,
                "machine journal recovery anchor prefix_sha256",
            )
            if type(prefix_size) is not int or prefix_size <= 0:
                raise MachineIntegrityError(
                    "machine journal recovery anchor prefix size is invalid"
                )
            anchor_path = self._anchor_path(commit.machine_id)
            staging = anchor_path.with_suffix(".tmp")
            encoded = encode_checksummed_document(
                _MACHINE_JOURNAL_RECOVERY_ANCHOR_SCHEMA,
                {
                    "machine_id": commit.machine_id,
                    "prefix_size": prefix_size,
                    "prefix_sha256": prefix_sha256,
                    "anchor_commit": anchor_document,
                    "has_emitted": bool(has_emitted),
                    "structured_state_enabled": bool(
                        structured_state_enabled
                    ),
                },
            )
            # Recovery anchors are disposable acceleration artifacts, not
            # accepted-transition authority. Atomic rename prevents readers
            # from observing a partial document; an OS crash may lose this
            # sidecar entirely, in which case cold open simply full-replays
            # the authoritative journal. Do not pay a second fsync barrier.
            try:
                staging.unlink(missing_ok=True)
                staging.write_bytes(encoded)
                staging.replace(anchor_path)
            finally:
                staging.unlink(missing_ok=True)
        except OSError:
            # The journal commit is already authoritative. Losing a derived
            # accelerator must not turn a successful transition into ambiguity.
            return

    def _read_authoritative(
        self,
        machine_id: str,
        *,
        force_full: bool = False,
    ) -> _DirectoryJournalCache:
        path = self._log_path(machine_id)
        before = self._file_identity(path)
        if before is None:
            return _DirectoryJournalCache(_JournalHistory(), None, False)
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise MachineIntegrityError(
                f"cannot read machine journal: {path}"
            ) from exc
        after = self._file_identity(path)
        if after != before:
            raise MachineIntegrityError(
                "machine journal changed during authoritative read"
            )
        if raw and not raw.endswith(b"\n"):
            raise MachineIntegrityError(
                "machine journal contains a torn trailing record"
            )

        if not force_full:
            accelerated = self._load_recovery_anchor(
                machine_id,
                raw=raw,
                path=path,
                file_identity=after,
            )
            if accelerated is not None:
                return accelerated

        history = _JournalHistory()
        previous_state: object | None = None
        structured_state_enabled = False
        try:
            for line in raw.splitlines():
                if not line:
                    continue
                if len(line) > self._structured_state_threshold_bytes:
                    structured_state_enabled = True
                commit = self._decode_line(
                    line,
                    machine_id=machine_id,
                    path=path,
                    previous_state=previous_state,
                )
                history.accept(commit)
                previous_state = commit.state
        except MachineConflict as exc:
            raise MachineIntegrityError(
                f"machine journal chain is invalid: {path}"
            ) from exc
        return _DirectoryJournalCache(
            history,
            after,
            structured_state_enabled,
            history_complete=True,
            prefix_hasher=sha256(raw),
            prefix_size=len(raw),
        )

    def close(self) -> None:
        """Release journal-local resources.

        Accepted records use the canonical durable append primitive and do not
        retain process-owned file descriptors.
        """

        return None

    def _authoritative_cache_locked(
        self,
        machine_id: str,
        *,
        require_full: bool = False,
    ) -> _DirectoryJournalCache:
        current_identity = self._file_identity(
            self._log_path(machine_id)
        )
        cached = self._cache.get(machine_id)
        if cached is not None:
            previous = cached.file_identity
            if (
                previous == current_identity
                and (not require_full or cached.history_complete)
            ):
                return cached
            if previous is not None:
                if current_identity is None:
                    raise MachineIntegrityError(
                        "machine journal disappeared after being observed"
                    )
                previous_size, _pm, _pc, previous_dev, previous_ino = previous
                current_size, _cm, _cc, current_dev, current_ino = (
                    current_identity
                )
                if (previous_dev, previous_ino) != (
                    current_dev,
                    current_ino,
                ):
                    raise MachineIntegrityError(
                        "machine journal file identity was replaced"
                    )
                if current_size < previous_size:
                    raise MachineIntegrityError(
                        "machine journal was truncated"
                    )
        rebuilt = self._read_authoritative(
            machine_id,
            force_full=require_full,
        )
        self._cache[machine_id] = rebuilt
        return rebuilt

    def _project_history(
        self,
        machine_id: str,
        projector,
        *,
        require_full: bool = False,
    ):
        # Project one validated cache value without copying full history.
        if type(machine_id) is not str or not machine_id.strip():
            raise ValueError("machine_id is required")
        if self._retirement_path(machine_id).exists():
            raise MachineIntegrityError(
                "machine journal identity is retired"
            )
        path = self._log_path(machine_id)
        identity = self._file_identity(path)
        with self._cache_lock:
            cached = self._cache.get(machine_id)
            if (
                cached is not None
                and cached.file_identity == identity
                and (not require_full or cached.history_complete)
            ):
                return projector(cached.history)

        with InterprocessFileLock(self._lock_path(machine_id)):
            with self._cache_lock:
                return projector(
                    self._authoritative_cache_locked(
                        machine_id,
                        require_full=require_full,
                    ).history
                )

    def _history(self, machine_id: str) -> tuple[MachineCommit, ...]:
        return self._project_history(
            machine_id,
            lambda history: history.snapshot(),
            require_full=True,
        )

    def append(self, commit: MachineCommit) -> MachineCommit:
        if not isinstance(commit, MachineCommit):
            raise TypeError("machine journal accepts MachineCommit")
        path = self._log_path(commit.machine_id)
        with InterprocessFileLock(self._lock_path(commit.machine_id)):
            if self._load_retirement(commit.machine_id) is not None:
                raise MachineConflict(
                    "machine journal identity is retired and cannot accept new commits"
                )
            with self._cache_lock:
                cached = self._authoritative_cache_locked(
                    commit.machine_id
                )
                if (
                    not cached.history_complete
                    and (
                        canonical_bytes(commit.command_id)
                        in cached.prefix_command_tokens
                        or canonical_bytes(commit.commit_id)
                        in cached.prefix_commit_tokens
                    )
                ):
                    cached = self._authoritative_cache_locked(
                        commit.machine_id,
                        require_full=True,
                    )
                existing = cached.history.validate_next(commit)
                if existing is not None:
                    return existing
                payload = (
                    canonical_bytes(
                        _commit_document(
                            commit,
                            previous_state=(
                                None
                                if not cached.history.commits
                                else cached.history.commits[-1].state
                            ),
                            force_snapshot=(
                                not cached.structured_state_enabled
                                or commit.revision % self._state_snapshot_interval == 0
                            ),
                        )
                    ) + b"\n"
                )

            # The exact per-machine lock remains held while the accepted record
            # crosses its durability barrier. The process-wide cache lock does
            # not: unrelated Machines are independent durability streams and
            # must be able to fsync concurrently.
            durable_append_bytes(path, payload)

            with self._cache_lock:
                authoritative = self._cache.get(commit.machine_id)
                if authoritative is not cached:
                    raise MachineIntegrityError(
                        "machine journal cache authority changed during durable append"
                    )
                cached.history.accept(commit)
                if len(payload) > self._structured_state_threshold_bytes:
                    cached.structured_state_enabled = True
                cached.prefix_hasher.update(payload)
                cached.prefix_size += len(payload)
                cached.file_identity = self._file_identity(path)
                if cached.file_identity is None:
                    raise MachineIntegrityError(
                        "machine journal disappeared after durable append"
                    )
                if cached.file_identity[0] != cached.prefix_size:
                    raise MachineIntegrityError(
                        "machine journal byte size drifted from incremental digest"
                    )
                has_emitted = cached.history.has_emitted
                structured_state_enabled = cached.structured_state_enabled
                prefix_size = cached.prefix_size
                prefix_sha256 = cached.prefix_hasher.copy().hexdigest()

            self._publish_recovery_anchor(
                commit,
                committed_payload=payload,
                prefix_size=prefix_size,
                prefix_sha256=prefix_sha256,
                has_emitted=has_emitted,
                structured_state_enabled=structured_state_enabled,
            )
            return commit

    def head(
        self,
        machine_id: str,
    ) -> tuple[MachineCommit | None, bool]:
        return self._project_history(
            machine_id,
            lambda history: (
                None if not history.commits else history.commits[-1],
                history.has_emitted,
            ),
        )

    def latest(self, machine_id: str) -> MachineCommit | None:
        return self.head(machine_id)[0]

    def get(self, commit_id: str) -> MachineCommit | None:
        if type(commit_id) is not str or not commit_id.strip():
            raise ValueError("commit_id is required")

        # A cache hit is never durable authority. Include previously observed
        # machines so disappearance/replacement is detected, then refresh every
        # candidate through the exact journal file identity before returning.
        with self._cache_lock:
            cached_machine_ids = tuple(self._cache)
        machine_ids = tuple(
            sorted(set(cached_machine_ids).union(self._machine_ids()))
        )
        token = canonical_bytes(commit_id)
        for machine_id in machine_ids:
            if self._retirement_path(machine_id).exists():
                continue
            path = self._log_path(machine_id)
            identity = self._file_identity(path)
            with InterprocessFileLock(self._lock_path(machine_id)):
                with self._cache_lock:
                    cached = self._cache.get(machine_id)
                    if cached is None or cached.file_identity != identity:
                        cached = self._authoritative_cache_locked(machine_id)
                    value = cached.history.by_commit_id.get(commit_id)
                    if value is not None:
                        return value
                    if cached.history_complete:
                        continue
                    if token not in cached.prefix_commit_tokens:
                        continue
                    cached = self._authoritative_cache_locked(
                        machine_id,
                        require_full=True,
                    )
                    value = cached.history.by_commit_id.get(commit_id)
                    if value is not None:
                        return value
        return None

    def command_commit(
        self,
        machine_id: str,
        command_id: str,
    ) -> MachineCommit | None:
        if type(machine_id) is not str or not machine_id.strip():
            raise ValueError("machine_id is required")
        if type(command_id) is not str or not command_id.strip():
            raise ValueError("command_id is required")
        if self._retirement_path(machine_id).exists():
            raise MachineIntegrityError(
                "machine journal identity is retired"
            )
        path = self._log_path(machine_id)
        identity = self._file_identity(path)
        with InterprocessFileLock(self._lock_path(machine_id)):
            with self._cache_lock:
                cached = self._cache.get(machine_id)
                if (
                    cached is None
                    or cached.file_identity != identity
                ):
                    cached = self._authoritative_cache_locked(machine_id)
                value = cached.history.by_command_id.get(command_id)
                if value is not None:
                    return value
                if cached.history_complete:
                    return None
                if (
                    canonical_bytes(command_id)
                    not in cached.prefix_command_tokens
                ):
                    return None
                cached = self._authoritative_cache_locked(
                    machine_id,
                    require_full=True,
                )
                return cached.history.by_command_id.get(command_id)

    def has_emitted_commands(self, machine_id: str) -> bool:
        return self._project_history(
            machine_id,
            lambda history: history.has_emitted,
        )

    def commits(self, machine_id: str) -> tuple[MachineCommit, ...]:
        return self._history(machine_id)

    def assess_gc(
        self,
        machine_id: str,
        *,
        closures: tuple[DurableCarrierReferenceClosure, ...] = (),
    ) -> MachineJournalGcAssessment:
        if (
            type(machine_id) is not str
            or not machine_id.strip()
            or machine_id != machine_id.strip()
        ):
            raise ValueError("machine journal GC machine_id must be canonical text")
        with InterprocessFileLock(self._lock_path(machine_id)):
            retirement = self._load_retirement(machine_id)
            if retirement is None:
                if self._quarantine_path(machine_id).exists():
                    raise MachineIntegrityError(
                        "machine journal quarantine exists without durable retirement proof"
                    )
                (
                    terminal_commit_id,
                    terminal_revision,
                    content_sha256,
                    byte_size,
                ) = self._gc_identity_locked(machine_id)
            else:
                terminal_commit_id = str(retirement["terminal_commit_id"])
                terminal_revision = int(retirement["terminal_revision"])
                content_sha256 = str(retirement["content_sha256"])
                byte_size = int(retirement["byte_size"])
            return MachineJournalGcAssessment(
                machine_id=machine_id,
                terminal_commit_id=terminal_commit_id,
                terminal_revision=terminal_revision,
                content_sha256=content_sha256,
                byte_size=byte_size,
                closures=closures,
            )

    @staticmethod
    def _require_retirement_matches_gc(
        retirement: dict[str, object],
        gc: MachineJournalGcAssessment,
    ) -> MachineJournalRetirementPhase:
        if (
            retirement["machine_id"] != gc.machine_id
            or retirement["terminal_commit_id"] != gc.terminal_commit_id
            or retirement["terminal_revision"] != gc.terminal_revision
            or retirement["content_sha256"] != gc.content_sha256
            or retirement["byte_size"] != gc.byte_size
        ):
            raise RuntimeError(
                "machine journal retirement identity changed across retry"
            )
        if retirement["gc_proof_digest"] != gc.proof_digest:
            raise RuntimeError(
                "machine journal GC proof changed across retry"
            )
        phase = retirement["phase"]
        if not isinstance(phase, MachineJournalRetirementPhase):
            raise MachineIntegrityError(
                "machine journal retirement phase is not typed"
            )
        return phase

    @staticmethod
    def _validate_quarantine_identity(
        quarantine: Path,
        gc: MachineJournalGcAssessment,
        *,
        expected_generation: FilesystemCarrierGeneration,
        same_object_only: bool = False,
    ) -> FilesystemCarrierGeneration:
        try:
            before = capture_filesystem_carrier_generation(
                quarantine,
                expected_kind=FilesystemCarrierKind.REGULAR_FILE,
            )
        except (OSError, RuntimeError) as exc:
            raise RuntimeError(
                "machine journal quarantine is not an owned regular file"
            ) from exc
        matches = (
            expected_generation.same_object(before)
            if same_object_only
            else expected_generation.same_generation(before)
        )
        if not matches:
            raise RuntimeError(
                "machine journal quarantine filesystem generation changed "
                "after retirement"
            )
        try:
            raw = quarantine.read_bytes()
        except OSError as exc:
            raise MachineIntegrityError(
                "cannot read quarantined machine journal"
            ) from exc
        try:
            after = capture_filesystem_carrier_generation(
                quarantine,
                expected_kind=FilesystemCarrierKind.REGULAR_FILE,
            )
        except (OSError, RuntimeError) as exc:
            raise MachineIntegrityError(
                "machine journal quarantine disappeared during verification"
            ) from exc
        if not before.same_generation(after):
            raise RuntimeError(
                "machine journal quarantine changed during verification"
            )
        if len(raw) != gc.byte_size or sha256(raw).hexdigest() != gc.content_sha256:
            raise RuntimeError(
                "machine journal quarantine identity changed after retirement"
            )
        return after

    @staticmethod
    def _move_journal_to_quarantine(path: Path, quarantine: Path) -> None:
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        fsync_directory(quarantine.parent.parent)
        if quarantine.exists():
            raise RuntimeError(
                "machine journal quarantine identity already exists"
            )
        try:
            path.rename(quarantine)
        except OSError:
            # Rename may have committed even if the caller lost the
            # acknowledgement. Only that exact postcondition is recoverable.
            if path.exists() or not quarantine.exists():
                raise
        fsync_directory(path.parent)
        fsync_directory(quarantine.parent)

    def purge(
        self,
        machine_id: str,
        *,
        gc: MachineJournalGcAssessment,
    ) -> bool:
        if (
            type(gc) is not MachineJournalGcAssessment
            or gc.machine_id != machine_id
        ):
            raise RuntimeError(
                "machine journal GC assessment does not bind the exact machine identity"
            )
        if not gc.eligible:
            raise RuntimeError(
                "machine journal GC requires complete execution, evidence, and recovery "
                "closure with zero retained references"
            )

        path = self._log_path(machine_id)
        quarantine = self._quarantine_path(machine_id)
        with InterprocessFileLock(self._lock_path(machine_id)):
            retirement = self._load_retirement(machine_id)
            if retirement is None:
                if quarantine.exists():
                    raise RuntimeError(
                        "machine journal quarantine exists without durable retirement proof"
                    )
                current = self._gc_identity_locked(machine_id)
                self._require_gc_identity(gc, current)
                carrier_generation = capture_filesystem_carrier_generation(
                    path,
                    expected_kind=FilesystemCarrierKind.REGULAR_FILE,
                )
                self._publish_retirement(
                    gc,
                    MachineJournalRetirementPhase.RETIRED,
                    carrier_generation=carrier_generation,
                )
                retirement = self._load_retirement(machine_id)
                if retirement is None:
                    raise MachineIntegrityError(
                        "machine journal retirement publication disappeared"
                    )

            phase = self._require_retirement_matches_gc(retirement, gc)
            carrier_generation = retirement["carrier_generation"]
            if not isinstance(
                carrier_generation,
                FilesystemCarrierGeneration,
            ):
                raise MachineIntegrityError(
                    "machine journal retirement carrier generation is not typed"
                )

            if phase is MachineJournalRetirementPhase.PURGED:
                if path.exists() or quarantine.exists():
                    raise RuntimeError(
                        "purged machine journal carrier reappeared as unowned residue"
                    )
                try:
                    self._anchor_path(machine_id).unlink(missing_ok=True)
                except OSError:
                    pass
                with self._cache_lock:
                    self._cache.pop(machine_id, None)
                return True

            if phase is MachineJournalRetirementPhase.RETIRED:
                if path.exists() and quarantine.exists():
                    raise RuntimeError(
                        "machine journal retirement split live/quarantine truth"
                    )
                if quarantine.exists():
                    # The rename committed but QUARANTINED publication did not.
                    quarantine_generation = self._validate_quarantine_identity(
                        quarantine,
                        gc,
                        expected_generation=carrier_generation,
                        same_object_only=True,
                    )
                    self._publish_retirement(
                        gc,
                        MachineJournalRetirementPhase.QUARANTINED,
                        carrier_generation=quarantine_generation,
                    )
                    carrier_generation = quarantine_generation
                    phase = MachineJournalRetirementPhase.QUARANTINED
                elif path.exists():
                    self._require_gc_identity(
                        gc,
                        self._gc_identity_locked(machine_id),
                    )
                    live_generation = capture_filesystem_carrier_generation(
                        path,
                        expected_kind=FilesystemCarrierKind.REGULAR_FILE,
                    )
                    if not carrier_generation.same_generation(live_generation):
                        raise RuntimeError(
                            "machine journal filesystem generation changed "
                            "after durable retirement"
                        )
                    self._move_journal_to_quarantine(path, quarantine)
                    quarantine_generation = self._validate_quarantine_identity(
                        quarantine,
                        gc,
                        expected_generation=carrier_generation,
                        same_object_only=True,
                    )
                    self._publish_retirement(
                        gc,
                        MachineJournalRetirementPhase.QUARANTINED,
                        carrier_generation=quarantine_generation,
                    )
                    carrier_generation = quarantine_generation
                    phase = MachineJournalRetirementPhase.QUARANTINED
                else:
                    raise RuntimeError(
                        "retired machine journal lost both live and quarantine carriers"
                    )

            if phase is MachineJournalRetirementPhase.QUARANTINED:
                if path.exists():
                    raise RuntimeError(
                        "quarantined machine journal live path reappeared as unowned residue"
                    )
                if quarantine.exists():
                    self._validate_quarantine_identity(
                        quarantine,
                        gc,
                        expected_generation=carrier_generation,
                    )
                    durable_unlink(quarantine)
                self._publish_retirement(
                    gc,
                    MachineJournalRetirementPhase.PURGED,
                    carrier_generation=carrier_generation,
                )
                try:
                    self._anchor_path(machine_id).unlink(missing_ok=True)
                except OSError:
                    pass
                with self._cache_lock:
                    self._cache.pop(machine_id, None)
                return True

            raise RuntimeError(
                f"unsupported machine journal retirement phase: {phase.value}"
            )

    def _machine_ids(self) -> tuple[str, ...]:
        ids: set[str] = set()
        for path in sorted(self.logs.glob("*.journal")):
            if (self.logs / ".retired" / f"{path.stem}.json").exists():
                continue
            lock_path = self.locks / f"{path.stem}.lock"
            with InterprocessFileLock(lock_path):
                try:
                    with path.open("rb") as handle:
                        line = handle.readline()
                except OSError as exc:
                    raise MachineIntegrityError(
                        f"cannot read machine journal: {path}"
                    ) from exc
                if not line:
                    continue
                if not line.endswith(b"\n"):
                    raise MachineIntegrityError(
                        "machine journal contains a torn first record"
                    )
                first_document = strict_json_loads(line[:-1])
                first_row = _require_object(
                    first_document,
                    "journal first commit",
                )
                machine_id = _require_text(
                    first_row.get("machine_id"),
                    "machine_id",
                )
                commit = self._decode_line(
                    line[:-1],
                    machine_id=machine_id,
                    path=path,
                    previous_state=None,
                )
                if self._file_key(commit.machine_id) != path.stem:
                    raise MachineIntegrityError(
                        "machine journal filename identity mismatch"
                    )
                ids.add(commit.machine_id)
        return tuple(sorted(ids))


__all__ = [
    "DirectoryMachineJournal",
    "InMemoryMachineJournal",
    "MachineJournalGcAssessment",
    "MachineJournalGcPort",
    "MachineJournalPort",
    "MachineJournalRetirementPhase",
]