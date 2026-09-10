from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.foundation.kernel.kernel import (
    DirectoryMachineSnapshotStore,
    InMemoryMachineSnapshotStore,
    MachineConflict,
    MachineIntegrityError,
    MachineProgramRef,
    MachineSnapshot,
    canonical_digest,
)


def make_snapshot(revision: int = 0, state: dict[str, object] | None = None) -> MachineSnapshot:
    return MachineSnapshot(
        machine_id="machine-1",
        revision=revision,
        program=MachineProgramRef(
            program_digest=canonical_digest({"program": "test"}),
            schema_id="schema.v1",
            program_kind="test",
            program_version="1",
        ),
        state=state or {"value": revision},
        parent_commit_id=None if revision == 0 else f"commit-{revision}",
    )


def test_memory_snapshot_store_is_monotonic() -> None:
    store = InMemoryMachineSnapshotStore()
    first = store.save(make_snapshot())
    assert store.save(first) == first
    with pytest.raises(MachineConflict):
        store.save(make_snapshot(state={"other": "value"}))


def test_directory_snapshot_store_round_trips(tmp_path: Path) -> None:
    first = make_snapshot()
    store = DirectoryMachineSnapshotStore(tmp_path)
    assert store.save(first) == first
    restored = DirectoryMachineSnapshotStore(tmp_path).load("machine-1")
    assert restored == first


def test_directory_snapshot_store_rejects_tampering(tmp_path: Path) -> None:
    store = DirectoryMachineSnapshotStore(tmp_path)
    store.save(make_snapshot())
    path = next((tmp_path / "snapshots").glob("*.json"))
    path.write_bytes(path.read_bytes().replace(b'"state"', b' "state"', 1))
    with pytest.raises(MachineIntegrityError):
        DirectoryMachineSnapshotStore(tmp_path).load("machine-1")
