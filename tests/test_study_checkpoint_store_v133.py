from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
import hashlib
import tempfile
import threading

import pytest

from noetrium_platform.foundation.kernel.kernel import ComponentIdentity
from noetrium_platform.capabilities.participant.core.api import ParticipantCheckpoint
from noetrium_platform.capabilities.participant.core.api import ParticipantImplementationIdentity, ParticipantRuntimeBinding
from noetrium_platform.research.experimentation.lifecycle.api import (
    RunCheckpointConflict,
    RunCheckpointManifest,
    RunParticipantPayload,
    RunParticipantSnapshotRef,
)
from noetrium_platform.research.experimentation.lifecycle.checkpoint.providers.directory_store import DirectoryRunCheckpointStore
from tests_support import runtime_identity_for_test


def participant_payload(role: str, payload: bytes, *, generation: str) -> RunParticipantPayload:
    implementation = ParticipantImplementationIdentity(
        "test", role, "1", "1", "1", hashlib.sha256(f"{role}-artifact".encode()).hexdigest()
    )
    binding = ParticipantRuntimeBinding(role, implementation, runtime_identity_for_test("test"), f"{role}-config")
    component = ComponentIdentity(
        f"participant.{role}", implementation.digest(), "1", "1", f"{role}-config"
    )
    checkpoint = ParticipantCheckpoint.capture(
        binding=binding, component=component, session_id="session", opaque_payload=payload
    )
    ref = RunParticipantSnapshotRef(checkpoint=checkpoint.ref, generation=generation)
    return RunParticipantPayload(ref, checkpoint)


def manifest(payloads: tuple[RunParticipantPayload, ...], *, checkpoint_id="cp1"):
    return RunCheckpointManifest(
        checkpoint_id=checkpoint_id,
        schema_version="4",
        experiment_spec_digest="study-digest",
        run_id="run",
        session_id="session",
        decision_cycle_id="dc",
        cycle_identity_digest="cycle-digest",
        participant_snapshots=tuple(row.ref for row in payloads),
    )


def test_directory_checkpoint_store_round_trip_and_idempotent_publish():
    with tempfile.TemporaryDirectory() as td:
        payloads=(
            participant_payload("method", b"method", generation="mg"),
            participant_payload("environment", b"environment", generation="eg"),
        )
        m=manifest(payloads)
        store=DirectoryRunCheckpointStore(Path(td))
        assert store.publish(m,payloads) == m
        assert store.publish(m,payloads) == m
        loaded=store.load("cp1")
        assert loaded.manifest == m
        assert loaded.participant_payloads == payloads


def test_checkpoint_id_cannot_be_rebound_to_different_state():
    with tempfile.TemporaryDirectory() as td:
        store=DirectoryRunCheckpointStore(Path(td))
        p1=(participant_payload("method", b"m1", generation="g1"),)
        m1=manifest(p1)
        store.publish(m1,p1)
        p2=(participant_payload("method", b"m2", generation="g2"),)
        m2=manifest(p2)
        with pytest.raises(RunCheckpointConflict):
            store.publish(m2,p2)



def test_checkpoint_publish_fences_conflicting_concurrent_writers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import noetrium_platform.research.experimentation.lifecycle.checkpoint.providers.directory_store as store_module

    root = tmp_path / "checkpoint-race"
    first_store = DirectoryRunCheckpointStore(root)
    second_store = DirectoryRunCheckpointStore(root)
    first_payloads = (
        participant_payload("method", b"first", generation="g1"),
    )
    second_payloads = (
        participant_payload("method", b"second", generation="g2"),
    )
    first_manifest = manifest(first_payloads, checkpoint_id="shared-checkpoint")
    second_manifest = manifest(second_payloads, checkpoint_id="shared-checkpoint")

    real_atomic_replace = store_module.atomic_replace_bytes
    first_manifest_write_entered = threading.Event()
    allow_first_manifest_write = threading.Event()
    manifest_write_count = 0
    manifest_write_lock = threading.Lock()

    def gate_first_manifest_write(path, payload):
        nonlocal manifest_write_count
        if path.parent == first_store.manifests:
            with manifest_write_lock:
                manifest_write_count += 1
                ordinal = manifest_write_count
            if ordinal == 1:
                first_manifest_write_entered.set()
                if not allow_first_manifest_write.wait(timeout=5.0):
                    raise TimeoutError("test did not release first manifest writer")
        return real_atomic_replace(path, payload)

    monkeypatch.setattr(
        store_module,
        "atomic_replace_bytes",
        gate_first_manifest_write,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(
            first_store.publish,
            first_manifest,
            first_payloads,
        )
        assert first_manifest_write_entered.wait(timeout=5.0)
        second_future = executor.submit(
            second_store.publish,
            second_manifest,
            second_payloads,
        )

        with pytest.raises(FutureTimeoutError):
            second_future.result(timeout=0.2)

        allow_first_manifest_write.set()
        assert first_future.result(timeout=5.0) == first_manifest
        with pytest.raises(RunCheckpointConflict):
            second_future.result(timeout=5.0)

    loaded = DirectoryRunCheckpointStore(root).load("shared-checkpoint")
    assert loaded.manifest == first_manifest
    assert loaded.participant_payloads == first_payloads
    losing_digest = second_payloads[0].checkpoint.ref.payload_sha256
    assert not first_store._blob_path(losing_digest).exists()



def test_checkpoint_publish_intent_survives_manifest_crash_and_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import noetrium_platform.research.experimentation.lifecycle.checkpoint.providers.directory_store as store_module

    root = tmp_path / "checkpoint-intent-crash"
    store = DirectoryRunCheckpointStore(root)
    payloads = (
        participant_payload("method", b"owned-payload", generation="g1"),
    )
    owned = manifest(payloads, checkpoint_id="intent-owned")

    real_atomic_replace = store_module.atomic_replace_bytes
    failed = False

    def fail_manifest_once(path, payload):
        nonlocal failed
        if path.parent == store.manifests and not failed:
            failed = True
            raise OSError("simulated crash before manifest publication")
        return real_atomic_replace(path, payload)

    monkeypatch.setattr(
        store_module,
        "atomic_replace_bytes",
        fail_manifest_once,
    )
    with pytest.raises(OSError, match="before manifest publication"):
        store.publish(owned, payloads)

    intent_path = store._intents._path(owned.checkpoint_id)
    assert intent_path.exists()
    assert not store._manifest_path(owned.checkpoint_id).exists()
    assert store._blob_path(
        payloads[0].checkpoint.ref.payload_sha256
    ).exists()

    conflicting_payloads = (
        participant_payload("method", b"losing-payload", generation="g2"),
    )
    conflicting = manifest(
        conflicting_payloads,
        checkpoint_id=owned.checkpoint_id,
    )
    with pytest.raises(RunCheckpointConflict):
        DirectoryRunCheckpointStore(root).publish(
            conflicting,
            conflicting_payloads,
        )
    assert not store._blob_path(
        conflicting_payloads[0].checkpoint.ref.payload_sha256
    ).exists()

    monkeypatch.setattr(
        store_module,
        "atomic_replace_bytes",
        real_atomic_replace,
    )
    reopened = DirectoryRunCheckpointStore(root)
    assert reopened.publish(owned, payloads) == owned
    assert not reopened._intents._path(owned.checkpoint_id).exists()
    assert reopened.load(owned.checkpoint_id).manifest == owned


def test_checkpoint_publish_retry_clears_intent_after_manifest_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import noetrium_platform.research.experimentation.lifecycle.checkpoint.providers.publication_intent as intent_module

    root = tmp_path / "checkpoint-intent-clear"
    store = DirectoryRunCheckpointStore(root)
    payloads = (
        participant_payload("method", b"payload", generation="g1"),
    )
    owned = manifest(payloads, checkpoint_id="intent-clear")

    real_durable_unlink = intent_module.durable_unlink
    failed = False

    def fail_clear_once(path):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("simulated crash after manifest commit")
        return real_durable_unlink(path)

    monkeypatch.setattr(
        intent_module,
        "durable_unlink",
        fail_clear_once,
    )
    with pytest.raises(OSError, match="after manifest commit"):
        store.publish(owned, payloads)

    assert store._manifest_path(owned.checkpoint_id).exists()
    assert store._intents._path(owned.checkpoint_id).exists()

    monkeypatch.setattr(
        intent_module,
        "durable_unlink",
        real_durable_unlink,
    )
    reopened = DirectoryRunCheckpointStore(root)
    assert reopened.publish(owned, payloads) == owned
    assert not reopened._intents._path(owned.checkpoint_id).exists()
