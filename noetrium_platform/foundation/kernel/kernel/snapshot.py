"""Snapshot persistence for Machine runtimes.

Snapshots are acceleration/recovery records, never a second authority.  The
journal head remains the only accepted-transition source of truth.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import Protocol, runtime_checkable

from .canonical import canonical_bytes, strict_json_loads, thaw_json
from .durability import InterprocessFileLock, atomic_replace_bytes
from .machine import (
    MachineConflict,
    MachineIntegrityError,
    MachineProgramRef,
    MachineSnapshot,
    ProgramLock,
)


def _snapshot_document(snapshot: MachineSnapshot) -> dict[str, object]:
    return {
        "machine_id": snapshot.machine_id,
        "revision": snapshot.revision,
        "program": {
            "program_digest": snapshot.program.program_digest,
            "schema_id": snapshot.program.schema_id,
            "program_kind": snapshot.program.program_kind,
            "program_version": snapshot.program.program_version,
            "program_lock": {
                "code_digest": snapshot.program.program_lock.code_digest,
                "dependency_digest": snapshot.program.program_lock.dependency_digest,
                "schema_digest": snapshot.program.program_lock.schema_digest,
                "interpreter_digest": snapshot.program.program_lock.interpreter_digest,
                "data_digest": snapshot.program.program_lock.data_digest,
                "config_digest": snapshot.program.program_lock.config_digest,
                "lock_digest": snapshot.program.program_lock.lock_digest,
            },
        },
        "state": thaw_json(snapshot.state),
        "parent_commit_id": snapshot.parent_commit_id,
        "snapshot_id": snapshot.snapshot_id,
    }


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise MachineIntegrityError(f"{label} must be an object")
    return value


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise MachineIntegrityError(f"{label} must be non-empty text")
    return value


def _revision(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise MachineIntegrityError(f"{label} must be non-negative integer")
    return value


def _decode_snapshot(value: object) -> MachineSnapshot:
    row = _object(value, "machine snapshot")
    if set(row) != {"machine_id", "revision", "program", "state", "parent_commit_id", "snapshot_id"}:
        raise MachineIntegrityError("machine snapshot fields are not exact")
    program = _object(row["program"], "machine snapshot program")
    if set(program) != {
        "program_digest", "schema_id", "program_kind", "program_version",
        "program_lock",
    }:
        raise MachineIntegrityError("machine snapshot program fields are not exact")
    lock = _object(program["program_lock"], "machine snapshot program_lock")
    if set(lock) != {
        "code_digest", "dependency_digest", "schema_digest",
        "interpreter_digest", "data_digest", "config_digest", "lock_digest",
    }:
        raise MachineIntegrityError("machine snapshot program_lock fields are not exact")
    program_lock = ProgramLock(
        code_digest=_text(lock["code_digest"], "code_digest"),
        dependency_digest=_text(lock["dependency_digest"], "dependency_digest"),
        schema_digest=_text(lock["schema_digest"], "schema_digest"),
        interpreter_digest=_text(lock["interpreter_digest"], "interpreter_digest"),
        data_digest=_text(lock["data_digest"], "data_digest"),
        config_digest=_text(lock["config_digest"], "config_digest"),
    )
    if program_lock.lock_digest != _text(lock["lock_digest"], "lock_digest"):
        raise MachineIntegrityError("machine snapshot program_lock digest mismatch")
    snapshot = MachineSnapshot(
        machine_id=_text(row["machine_id"], "machine_id"),
        revision=_revision(row["revision"], "revision"),
        program=MachineProgramRef(
            program_digest=_text(program["program_digest"], "program_digest"),
            schema_id=_text(program["schema_id"], "schema_id"),
            program_kind=_text(program["program_kind"], "program_kind"),
            program_version=_text(program["program_version"], "program_version"),
            program_lock=program_lock,
        ),
        state=row["state"],  # type: ignore[arg-type]
        parent_commit_id=row["parent_commit_id"],  # type: ignore[arg-type]
    )
    if snapshot.snapshot_id != _text(row["snapshot_id"], "snapshot_id"):
        raise MachineIntegrityError("machine snapshot digest mismatch")
    return snapshot
@runtime_checkable
class MachineSnapshotStorePort(Protocol):
    def save(self, snapshot: MachineSnapshot) -> MachineSnapshot: ...
    def load(self, machine_id: str) -> MachineSnapshot | None: ...


class InMemoryMachineSnapshotStore(MachineSnapshotStorePort):
    """Process-local snapshot store for tests and embedded deployments."""

    durability = "process_local"

    def __init__(self) -> None:
        self._latest: dict[str, MachineSnapshot] = {}
        self._lock = RLock()

    def save(self, snapshot: MachineSnapshot) -> MachineSnapshot:
        if not isinstance(snapshot, MachineSnapshot):
            raise TypeError("snapshot store accepts MachineSnapshot")
        with self._lock:
            current = self._latest.get(snapshot.machine_id)
            if current is not None and snapshot.revision < current.revision:
                raise MachineConflict("snapshot revision cannot move backwards")
            if current is not None and snapshot.revision == current.revision:
                if current.snapshot_id != snapshot.snapshot_id:
                    raise MachineConflict("snapshot conflict at the same revision")
                return current
            self._latest[snapshot.machine_id] = snapshot
            return snapshot

    def load(self, machine_id: str) -> MachineSnapshot | None:
        if type(machine_id) is not str or not machine_id.strip():
            raise ValueError("snapshot machine_id is required")
        with self._lock:
            return self._latest.get(machine_id)


class DirectoryMachineSnapshotStore(MachineSnapshotStorePort):
    """Crash-durable one-head-per-machine snapshot store."""

    durability = "crash_durable"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.snapshots = self.root / "snapshots"
        self.locks = self.root / "locks"
        self.snapshots.mkdir(parents=True, exist_ok=True)
        self.locks.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, MachineSnapshot] = {}
        self._cache_lock = RLock()

    @staticmethod
    def _key(machine_id: str) -> str:
        return sha256(machine_id.encode("utf-8")).hexdigest()

    def _path(self, machine_id: str) -> Path:
        return self.snapshots / f"{self._key(machine_id)}.json"

    def _lock_path(self, machine_id: str) -> Path:
        return self.locks / f"{self._key(machine_id)}.snapshot.lock"

    def _read(self, machine_id: str) -> MachineSnapshot | None:
        path = self._path(machine_id)
        if not path.exists():
            return None
        try:
            raw = path.read_bytes()
            value = strict_json_loads(raw)
            if canonical_bytes(value) != raw:
                raise MachineIntegrityError("machine snapshot is not canonical JSON")
            snapshot = _decode_snapshot(value)
        except MachineIntegrityError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise MachineIntegrityError(f"cannot read machine snapshot: {path}") from exc
        if snapshot.machine_id != machine_id:
            raise MachineIntegrityError("machine snapshot identity mismatch")
        return snapshot

    def save(self, snapshot: MachineSnapshot) -> MachineSnapshot:
        if not isinstance(snapshot, MachineSnapshot):
            raise TypeError("snapshot store accepts MachineSnapshot")
        with InterprocessFileLock(self._lock_path(snapshot.machine_id)):
            current = self._read(snapshot.machine_id)
            if current is not None and snapshot.revision < current.revision:
                raise MachineConflict("snapshot revision cannot move backwards")
            if current is not None and snapshot.revision == current.revision:
                if current.snapshot_id != snapshot.snapshot_id:
                    raise MachineConflict("snapshot conflict at the same revision")
                return current
            atomic_replace_bytes(self._path(snapshot.machine_id), canonical_bytes(_snapshot_document(snapshot)))
            with self._cache_lock:
                self._cache[snapshot.machine_id] = snapshot
            return snapshot

    def load(self, machine_id: str) -> MachineSnapshot | None:
        if type(machine_id) is not str or not machine_id.strip():
            raise ValueError("snapshot machine_id is required")
        with self._cache_lock:
            cached = self._cache.get(machine_id)
        if cached is not None:
            return cached
        snapshot = self._read(machine_id)
        if snapshot is not None:
            with self._cache_lock:
                self._cache[machine_id] = snapshot
        return snapshot


__all__ = [
    "DirectoryMachineSnapshotStore",
    "InMemoryMachineSnapshotStore",
    "MachineSnapshotStorePort",
]
