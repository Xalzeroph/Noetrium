"""Journal authorities for accepted Machine transitions.

The journal is the source of accepted facts. Workers only propose; a journal
accepts one monotonic revision per machine and rejects ambiguous duplicates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
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
    InterprocessFileLock,
    atomic_replace_bytes,
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


def _commit_document(commit: MachineCommit) -> dict[str, object]:
    return {
        "machine_id": commit.machine_id,
        "command_id": commit.command_id,
        "base_revision": commit.base_revision,
        "revision": commit.revision,
        "proposal_digest": commit.proposal_digest,
        "command_digest": commit.command_digest,
        "state": thaw_json(commit.state),
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


def _decode_commit(value: object) -> MachineCommit:
    row = _require_object(value, "journal commit")
    _require_exact(row, {
        "machine_id", "command_id", "base_revision", "revision",
        "proposal_digest", "command_digest", "state", "output_refs", "event_payloads",
        "effect_intent_refs", "emitted_commands", "previous_commit_id", "before_state_digest",
        "input_digest", "program_digest", "program_lock_digest", "machine_kind", "machine_version", "input_refs",
        "state_delta_ref", "evidence_refs", "artifact_refs", "parent_transition_id", "attempt_id",
        "authority_epoch", "child_links", "accepted_status",
    }, "journal commit")
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
        state=row["state"],  # type: ignore[arg-type]
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
    return commit



_MACHINE_JOURNAL_RETIREMENT_SCHEMA = "machine.journal-retirement.v1"
_MACHINE_JOURNAL_RETIREMENT_FIELDS = {
    "machine_id",
    "terminal_commit_id",
    "terminal_revision",
    "content_sha256",
    "byte_size",
    "gc_proof_digest",
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
    def latest(self, machine_id: str) -> MachineCommit | None: ...
    def get(self, commit_id: str) -> MachineCommit | None: ...
    def commits(self, machine_id: str) -> tuple[MachineCommit, ...]: ...


class _JournalHistory:
    """Validated in-process projection of one append-only Machine journal."""

    __slots__ = ("commits", "by_command_id", "by_commit_id")

    def __init__(
        self,
        commits: list[MachineCommit] | None = None,
    ) -> None:
        self.commits: list[MachineCommit] = []
        self.by_command_id: dict[str, MachineCommit] = {}
        self.by_commit_id: dict[str, MachineCommit] = {}
        for commit in commits or ():
            self.accept(commit)

    def clone(self) -> "_JournalHistory":
        value = _JournalHistory()
        value.commits = list(self.commits)
        value.by_command_id = dict(self.by_command_id)
        value.by_commit_id = dict(self.by_commit_id)
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
        return commit

    def snapshot(self) -> tuple[MachineCommit, ...]:
        return tuple(self.commits)


@runtime_checkable
class MachineJournalPort(Protocol):
    def append(self, commit: MachineCommit) -> MachineCommit: ...
    def latest(self, machine_id: str) -> MachineCommit | None: ...
    def get(self, commit_id: str) -> MachineCommit | None: ...
    def commits(self, machine_id: str) -> tuple[MachineCommit, ...]: ...


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

    def latest(self, machine_id: str) -> MachineCommit | None:
        if type(machine_id) is not str or not machine_id.strip():
            raise ValueError("machine_id is required")
        with self._lock:
            history = self._histories.get(machine_id)
            if history is None or not history.commits:
                return None
            return history.commits[-1]

    def get(self, commit_id: str) -> MachineCommit | None:
        with self._lock:
            return self._by_id.get(commit_id)

    def commits(self, machine_id: str) -> tuple[MachineCommit, ...]:
        with self._lock:
            history = self._histories.get(machine_id)
            return () if history is None else history.snapshot()


class _DirectoryJournalCache:
    __slots__ = ("history", "file_identity")

    def __init__(
        self,
        history: _JournalHistory,
        file_identity: tuple[int, int, int, int, int] | None,
    ) -> None:
        self.history = history
        self.file_identity = file_identity


class DirectoryMachineJournal(MachineJournalPort, MachineJournalGcPort):
    """Crash-durable append-only journal with derived incremental acceleration.

    The journal file remains the sole authority. The in-process cache is
    discarded and rebuilt from the complete canonical file whenever another
    writer changes that file. Repeated appends by the same authority therefore
    avoid O(history) rescans without introducing a sidecar truth source.
    """

    durability = "crash_durable"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.logs = self.root / "machines"
        self.locks = self.root / "locks"
        self.logs.mkdir(parents=True, exist_ok=True)
        self.locks.mkdir(parents=True, exist_ok=True)
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
            "phase": phase,
        }

    def _publish_retirement(
        self,
        gc: MachineJournalGcAssessment,
        phase: MachineJournalRetirementPhase,
    ) -> None:
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
    ) -> MachineCommit:
        try:
            document = strict_json_loads(line)
            commit = _decode_commit(document)
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

    def _read_authoritative(
        self,
        machine_id: str,
    ) -> _DirectoryJournalCache:
        path = self._log_path(machine_id)
        before = self._file_identity(path)
        if before is None:
            return _DirectoryJournalCache(_JournalHistory(), None)
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
        history = _JournalHistory()
        try:
            for line in raw.splitlines():
                if not line:
                    continue
                history.accept(
                    self._decode_line(
                        line,
                        machine_id=machine_id,
                        path=path,
                    )
                )
        except MachineConflict as exc:
            raise MachineIntegrityError(
                f"machine journal chain is invalid: {path}"
            ) from exc
        return _DirectoryJournalCache(history, after)

    def _authoritative_cache_locked(
        self,
        machine_id: str,
    ) -> _DirectoryJournalCache:
        current_identity = self._file_identity(
            self._log_path(machine_id)
        )
        cached = self._cache.get(machine_id)
        if cached is not None:
            previous = cached.file_identity
            if previous == current_identity:
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
        rebuilt = self._read_authoritative(machine_id)
        self._cache[machine_id] = rebuilt
        return rebuilt

    def _history(self, machine_id: str) -> tuple[MachineCommit, ...]:
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
            ):
                return cached.history.snapshot()

        with InterprocessFileLock(self._lock_path(machine_id)):
            with self._cache_lock:
                return self._authoritative_cache_locked(
                    machine_id
                ).history.snapshot()

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
                existing = cached.history.validate_next(commit)
                if existing is not None:
                    return existing
                payload = (
                    canonical_bytes(_commit_document(commit)) + b"\n"
                )
                durable_append_bytes(path, payload)
                cached.history.accept(commit)
                cached.file_identity = self._file_identity(path)
                if cached.file_identity is None:
                    raise MachineIntegrityError(
                        "machine journal disappeared after durable append"
                    )
                return commit

    def latest(self, machine_id: str) -> MachineCommit | None:
        history = self._history(machine_id)
        return None if not history else history[-1]

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
        for machine_id in machine_ids:
            self._history(machine_id)
            with self._cache_lock:
                value = self._cache[machine_id].history.by_commit_id.get(
                    commit_id
                )
                if value is not None:
                    return value
        return None

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
    ) -> None:
        if quarantine.is_symlink() or not quarantine.is_file():
            raise RuntimeError(
                "machine journal quarantine is not an owned regular file"
            )
        try:
            raw = quarantine.read_bytes()
        except OSError as exc:
            raise MachineIntegrityError(
                "cannot read quarantined machine journal"
            ) from exc
        if len(raw) != gc.byte_size or sha256(raw).hexdigest() != gc.content_sha256:
            raise RuntimeError(
                "machine journal quarantine identity changed after retirement"
            )

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
                self._publish_retirement(
                    gc,
                    MachineJournalRetirementPhase.RETIRED,
                )
                retirement = self._load_retirement(machine_id)
                if retirement is None:
                    raise MachineIntegrityError(
                        "machine journal retirement publication disappeared"
                    )

            phase = self._require_retirement_matches_gc(retirement, gc)

            if phase is MachineJournalRetirementPhase.PURGED:
                if path.exists() or quarantine.exists():
                    raise RuntimeError(
                        "purged machine journal carrier reappeared as unowned residue"
                    )
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
                    self._validate_quarantine_identity(quarantine, gc)
                    self._publish_retirement(
                        gc,
                        MachineJournalRetirementPhase.QUARANTINED,
                    )
                    phase = MachineJournalRetirementPhase.QUARANTINED
                elif path.exists():
                    self._require_gc_identity(
                        gc,
                        self._gc_identity_locked(machine_id),
                    )
                    self._move_journal_to_quarantine(path, quarantine)
                    self._validate_quarantine_identity(quarantine, gc)
                    self._publish_retirement(
                        gc,
                        MachineJournalRetirementPhase.QUARANTINED,
                    )
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
                    self._validate_quarantine_identity(quarantine, gc)
                    durable_unlink(quarantine)
                self._publish_retirement(
                    gc,
                    MachineJournalRetirementPhase.PURGED,
                )
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
                commit = self._decode_line(
                    line[:-1],
                    machine_id=_decode_commit(
                        strict_json_loads(line[:-1])
                    ).machine_id,
                    path=path,
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