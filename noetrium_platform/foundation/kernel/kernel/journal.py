"""Journal authorities for accepted Machine transitions.

The journal is the source of accepted facts. Workers only propose; a journal
accepts one monotonic revision per machine and rejects ambiguous duplicates.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from threading import RLock
from typing import Protocol, runtime_checkable

from .canonical import canonical_bytes, strict_json_loads, thaw_json
from .durability import InterprocessFileLock, durable_append_bytes
from .machine import (
    MachineCommand,
    MachineCommit,
    MachineConflict,
    MachineIntegrityError,
)


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


def _decode_commit(value: object) -> MachineCommit:
    row = _require_object(value, "journal commit")
    _require_exact(row, {
        "machine_id", "command_id", "base_revision", "revision",
        "proposal_digest", "command_digest", "state", "output_refs", "event_payloads",
        "effect_intent_refs", "emitted_commands", "previous_commit_id",
    }, "journal commit")
    output_refs = row["output_refs"]
    effect_refs = row["effect_intent_refs"]
    events = row["event_payloads"]
    commands = row["emitted_commands"]
    if not all(isinstance(item, list) for item in (output_refs, effect_refs, events, commands)):
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
    )
    return commit


@runtime_checkable
class MachineJournalPort(Protocol):
    def append(self, commit: MachineCommit) -> MachineCommit: ...
    def latest(self, machine_id: str) -> MachineCommit | None: ...
    def get(self, commit_id: str) -> MachineCommit | None: ...
    def commits(self, machine_id: str) -> tuple[MachineCommit, ...]: ...


class _JournalRules:
    @staticmethod
    def accept(
        history: list[MachineCommit],
        commit: MachineCommit,
    ) -> MachineCommit:
        for existing in history:
            if existing.command_id == commit.command_id:
                if existing == commit:
                    return existing
                raise MachineConflict(
                    f"command_id already committed with different payload: {commit.command_id}"
                )
            if existing.commit_id == commit.commit_id:
                return existing
        latest = history[-1] if history else None
        expected_base = 0 if latest is None else latest.revision
        if commit.base_revision != expected_base:
            raise MachineConflict(
                f"stale machine revision: expected={expected_base} actual={commit.base_revision}"
            )
        expected_previous = None if latest is None else latest.commit_id
        if commit.previous_commit_id != expected_previous:
            raise MachineConflict("machine commit previous_commit_id does not match journal head")
        history.append(commit)
        return commit


class InMemoryMachineJournal(MachineJournalPort):
    """Thread-safe journal authority for tests and embedded execution."""

    durability = "process_local"

    def __init__(self) -> None:
        self._histories: dict[str, list[MachineCommit]] = defaultdict(list)
        self._by_id: dict[str, MachineCommit] = {}
        self._lock = RLock()

    def append(self, commit: MachineCommit) -> MachineCommit:
        if not isinstance(commit, MachineCommit):
            raise TypeError("machine journal accepts MachineCommit")
        with self._lock:
            accepted = _JournalRules.accept(self._histories[commit.machine_id], commit)
            self._by_id[accepted.commit_id] = accepted
            return accepted

    def latest(self, machine_id: str) -> MachineCommit | None:
        if type(machine_id) is not str or not machine_id.strip():
            raise ValueError("machine_id is required")
        with self._lock:
            history = self._histories.get(machine_id, [])
            return None if not history else history[-1]

    def get(self, commit_id: str) -> MachineCommit | None:
        with self._lock:
            return self._by_id.get(commit_id)

    def commits(self, machine_id: str) -> tuple[MachineCommit, ...]:
        with self._lock:
            return tuple(self._histories.get(machine_id, ()))


class DirectoryMachineJournal(MachineJournalPort):
    """Crash-durable line journal with cross-process single-writer locking."""

    durability = "crash_durable"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.logs = self.root / "machines"
        self.locks = self.root / "locks"
        self.logs.mkdir(parents=True, exist_ok=True)
        self.locks.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, tuple[MachineCommit, ...]] = {}
        self._cache_lock = RLock()

    @staticmethod
    def _file_key(machine_id: str) -> str:
        from hashlib import sha256
        return sha256(machine_id.encode("utf-8")).hexdigest()

    def _log_path(self, machine_id: str) -> Path:
        return self.logs / f"{self._file_key(machine_id)}.journal"

    def _lock_path(self, machine_id: str) -> Path:
        return self.locks / f"{self._file_key(machine_id)}.lock"

    def _read(self, machine_id: str) -> list[MachineCommit]:
        path = self._log_path(machine_id)
        if not path.exists():
            return []
        result: list[MachineCommit] = []
        try:
            for line in path.read_bytes().splitlines():
                if not line:
                    continue
                document = strict_json_loads(line)
                commit = _decode_commit(document)
                if commit.machine_id != machine_id:
                    raise MachineIntegrityError("journal machine identity mismatch")
                if canonical_bytes(document) != line:
                    raise MachineIntegrityError("journal line is not canonical JSON")
                _JournalRules.accept(result, commit)
        except MachineIntegrityError:
            raise
        except MachineConflict as exc:
            raise MachineIntegrityError(f"machine journal chain is invalid: {path}") from exc
        except (OSError, TypeError, ValueError) as exc:
            raise MachineIntegrityError(f"cannot read machine journal: {path}") from exc
        return result

    def append(self, commit: MachineCommit) -> MachineCommit:
        if not isinstance(commit, MachineCommit):
            raise TypeError("machine journal accepts MachineCommit")
        with InterprocessFileLock(self._lock_path(commit.machine_id)):
            history = self._read(commit.machine_id)
            accepted = _JournalRules.accept(history, commit)
            if accepted is not commit:
                return accepted
            durable_append_bytes(
                self._log_path(commit.machine_id),
                canonical_bytes(_commit_document(commit)) + b"\n",
            )
            with self._cache_lock:
                self._cache[commit.machine_id] = tuple(history + [commit])
            return commit

    def _history(self, machine_id: str) -> tuple[MachineCommit, ...]:
        with self._cache_lock:
            cached = self._cache.get(machine_id)
        if cached is not None:
            return cached
        history = tuple(self._read(machine_id))
        with self._cache_lock:
            self._cache[machine_id] = history
        return history

    def latest(self, machine_id: str) -> MachineCommit | None:
        history = self._history(machine_id)
        return None if not history else history[-1]

    def get(self, commit_id: str) -> MachineCommit | None:
        if type(commit_id) is not str or not commit_id.strip():
            raise ValueError("commit_id is required")
        for machine_id in self._machine_ids():
            value = next((item for item in self._history(machine_id) if item.commit_id == commit_id), None)
            if value is not None:
                return value
        return None

    def commits(self, machine_id: str) -> tuple[MachineCommit, ...]:
        return self._history(machine_id)

    def _machine_ids(self) -> tuple[str, ...]:
        ids: set[str] = set()
        for path in self.logs.glob("*.journal"):
            for line in path.read_bytes().splitlines():
                if not line:
                    continue
                commit = _decode_commit(strict_json_loads(line))
                ids.add(commit.machine_id)
        return tuple(sorted(ids))


__all__ = [
    "DirectoryMachineJournal",
    "InMemoryMachineJournal",
    "MachineJournalPort",
]