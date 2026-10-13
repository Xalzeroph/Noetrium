"""Linear-chain event indexes preserve every fail-closed causal invariant."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from noetrium_platform.foundation.kernel.event import event_field
from noetrium_platform.foundation.kernel.event_store import FileCausalEventStore


def _store(tmp_path: Path) -> FileCausalEventStore:
    return FileCausalEventStore(tmp_path / "state.json", state_schema="test.linear-state")


def test_dense_index_replays_and_repairs_disposable_projection(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.exists() is False
    for generation in range(1, 7):
        store.append(f"state-{generation}".encode())
    assert [event_field(event, "generation") for event in store.events()] == list(range(1, 7))
    store.projection_path.write_bytes(b"stale projection")
    assert store.read() == b"state-6"
    assert store.verify_projection_rebuild() == b"state-6"


def test_misnamed_event_digest_is_never_accepted(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append(b"state-1")
    original, = store.event_root.glob("*.unit")
    alternate_digest = "0" * 64 if not original.name.endswith("0" * 64 + ".unit") else "1" * 64
    original.rename(store.event_root / (original.name[:21] + alternate_digest + ".unit"))
    with pytest.raises(RuntimeError, match="corrupt"):
        store.events()


def test_duplicate_event_generation_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append(b"state-1")
    original, = store.event_root.glob("*.unit")
    duplicate_name = original.name[:21] + ("a" * 64 if original.name[21:85] != "a" * 64 else "b" * 64) + ".unit"
    (store.event_root / duplicate_name).write_bytes(original.read_bytes())
    with pytest.raises(RuntimeError, match="generation is repeated"):
        store.events()


def test_missing_generation_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append(b"state-1")
    store.append(b"state-2")
    initial = sorted(store.event_root.glob("*.unit"))[0]
    initial.unlink()
    with pytest.raises(RuntimeError, match="not contiguous"):
        store.events()


def test_append_reuses_validated_prefix_without_rescanning_history(tmp_path: Path) -> None:
    store = _store(tmp_path)
    original = store._scan_events_unlocked
    scans = []

    def scan(*, collect):
        scans.append(True)
        return original(collect=collect)

    store._scan_events_unlocked = scan
    for number in range(24):
        store.append(f"sequence-{number}".encode())
    assert len(scans) == 1
    assert [event_field(event, "generation") for event in store.events()] == list(range(1, 25))


def test_peer_writer_invalidates_local_tail_cache(tmp_path: Path) -> None:
    writer = _store(tmp_path)
    peer = _store(tmp_path)
    writer.append(b"first")
    peer.append(b"second")
    writer.append(b"third")
    assert [event_field(event, "generation") for event in writer.events()] == [1, 2, 3]
    assert peer.read() == b"third"


def test_event_commit_survives_projection_write_failure(tmp_path: Path, monkeypatch) -> None:
    import noetrium_platform.foundation.kernel.event_store as module

    store = _store(tmp_path)
    durable_write = module.atomic_replace_bytes

    def fail_projection(path, payload):
        if path == store.projection_path:
            raise OSError("injected projection failure")
        return durable_write(path, payload)

    with monkeypatch.context() as patch:
        patch.setattr(module, "atomic_replace_bytes", fail_projection)
        with pytest.raises(OSError, match="projection failure"):
            store.append(b"committed-only-as-event")
    assert store.read() == b"committed-only-as-event"
    store.append(b"following-event")
    assert [event_field(event, "generation") for event in store.events()] == [1, 2]


def test_corrupt_cached_tail_must_fail_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append(b"state-1")
    event_path, = store.event_root.glob("*.unit")
    event_path.write_bytes(b"corrupted event")
    with pytest.raises(RuntimeError, match="corrupt"):
        store.append(b"state-2")


def test_external_process_commit_invalidates_local_prefix(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.append(b"before-peer")
    script = (
        "import sys; from pathlib import Path; "
        "from noetrium_platform.foundation.kernel.event_store import FileCausalEventStore; "
        "FileCausalEventStore(Path(sys.argv[1]), state_schema='test.linear-state').append(b'peer')"
    )
    subprocess.run([sys.executable, "-c", script, str(store.projection_path)], check=True)
    store.append(b"after-peer")
    assert [event_field(event, "generation") for event in store.events()] == [1, 2, 3]
    assert store.verify_projection_rebuild() == b"after-peer"


def test_simultaneous_process_writers_produce_one_dense_causal_chain(tmp_path: Path) -> None:
    store = _store(tmp_path)
    worker = (
        "import sys; from pathlib import Path; "
        "from noetrium_platform.foundation.kernel.event_store import FileCausalEventStore; "
        "journal = FileCausalEventStore(Path(sys.argv[1]), state_schema='test.linear-state'); "
        "[journal.append((sys.argv[2] + ':' + str(n)).encode()) for n in range(5)]"
    )
    children = [
        subprocess.Popen(
            [sys.executable, "-c", worker, str(store.projection_path), str(index)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        for index in range(4)
    ]
    try:
        for child in children:
            _output, errors = child.communicate(timeout=20)
            assert child.returncode == 0, errors
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
    events = store.events()
    assert [event_field(event, "generation") for event in events] == list(range(1, 21))
    assert len({event.unit_digest for event in events}) == 20
    assert store.read() == store.verify_projection_rebuild()


def test_incremental_append_does_not_reencode_cached_predecessor(tmp_path: Path, monkeypatch) -> None:
    import noetrium_platform.foundation.kernel.event_store as module

    store = _store(tmp_path)
    store.append(b"first")
    original = module.encode_unit
    encoded = []

    def counted(event):
        encoded.append(event.unit_digest)
        return original(event)

    monkeypatch.setattr(module, "encode_unit", counted)
    second = store.append(b"second")
    assert encoded == [second.unit_digest]
    assert store.verify_projection_rebuild() == b"second"


def test_latest_state_replays_full_chain_without_retaining_history(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    for generation in range(1, 18):
        store.append(f"state-{generation}".encode())
    original = store._scan_events_unlocked
    modes: list[bool] = []

    def observe(*, collect: bool):
        modes.append(collect)
        return original(collect=collect)

    monkeypatch.setattr(store, "_scan_events_unlocked", observe)
    assert store.read() == b"state-17"
    assert store.exists()
    assert store.verify_projection_rebuild() == b"state-17"
    assert modes == [False, False, False]
    assert len(store.events()) == 17
    assert modes == [False, False, False, True]


def test_tail_only_read_still_rejects_intermediate_event_corruption(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for generation in range(1, 6):
        store.append(f"state-{generation}".encode())
    middle = sorted(store.event_root.glob("*.unit"))[2]
    middle.write_bytes(b"corrupt middle of chain")
    with pytest.raises(RuntimeError, match="corrupt"):
        store.read()
    with pytest.raises(RuntimeError, match="corrupt"):
        store.verify_projection_rebuild()
    with pytest.raises(RuntimeError, match="corrupt"):
        store.append(b"should-not-append")
