from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
import hashlib
import tempfile
import threading

import pytest

from noetrium_platform.foundation.kernel.kernel import (
    ComponentIdentity,
    DurableCarrierClosureAuthority,
    DurableCarrierReferenceClosure,
)
from noetrium_platform.capabilities.participant.core.api import ParticipantCheckpoint
from noetrium_platform.capabilities.participant.core.api import ParticipantImplementationIdentity, ParticipantRuntimeBinding
from noetrium_platform.research.experimentation.lifecycle.api import (
    RunCheckpointConflict,
    RunCheckpointIntegrityError,
    RunCheckpointManifest,
    RunCheckpointRecoveryRequired,
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


def closed_gc(store: DirectoryRunCheckpointStore, checkpoint_id: str):
    return store.assess_gc(
        checkpoint_id,
        closures=(
            DurableCarrierReferenceClosure(
                DurableCarrierClosureAuthority.EVIDENCE,
                "1" * 64,
                (),
            ),
            DurableCarrierReferenceClosure(
                DurableCarrierClosureAuthority.EXECUTION,
                "2" * 64,
                (),
            ),
            DurableCarrierReferenceClosure(
                DurableCarrierClosureAuthority.RECOVERY,
                "3" * 64,
                (),
            ),
        ),
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

    pending = DirectoryRunCheckpointStore(root)
    with pytest.raises(RunCheckpointRecoveryRequired) as raised:
        pending.load(owned.checkpoint_id)
    recovery = raised.value
    assert recovery.checkpoint_id == owned.checkpoint_id
    assert recovery.namespace == "run"
    assert recovery.manifest_sha256 == pending._intents.load(
        owned.checkpoint_id
    ).manifest_sha256
    assert recovery.blob_sha256s == (
        payloads[0].checkpoint.ref.payload_sha256,
    )

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
    # The manifest is already durable, so an exact stale intent does not make
    # the checkpoint unreadable while retry is converging its cleanup.
    assert reopened.load(owned.checkpoint_id).manifest == owned
    assert reopened.publish(owned, payloads) == owned
    assert not reopened._intents._path(owned.checkpoint_id).exists()


def test_checkpoint_load_fails_closed_on_committed_intent_conflict(
    tmp_path: Path,
) -> None:
    from noetrium_platform.research.experimentation.lifecycle.checkpoint.providers.publication_intent import (
        CheckpointPublicationIntent,
    )

    store = DirectoryRunCheckpointStore(tmp_path / "committed-intent-conflict")
    payloads = (
        participant_payload("method", b"payload", generation="g1"),
    )
    owned = manifest(payloads, checkpoint_id="committed-intent-conflict")
    assert store.publish(owned, payloads) == owned

    store._intents.publish(
        CheckpointPublicationIntent(
            namespace=store._intents.namespace,
            checkpoint_id=owned.checkpoint_id,
            manifest_sha256="0" * 64,
            blob_sha256s=tuple(
                sorted(
                    {
                        item.checkpoint.ref.payload_sha256
                        for item in payloads
                    }
                )
            ),
        )
    )

    with pytest.raises(
        RunCheckpointIntegrityError,
        match="conflicts with pending publication intent",
    ):
        store.load(owned.checkpoint_id)


def test_checkpoint_blob_external_exact_create_race_is_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import noetrium_platform.research.experimentation.lifecycle.checkpoint.providers.directory_store as store_module

    store = DirectoryRunCheckpointStore(tmp_path / "blob-exact-race")
    payloads = (
        participant_payload("method", b"same-content", generation="g1"),
    )
    checkpoint = manifest(payloads, checkpoint_id="blob-exact-race")
    expected = payloads[0].checkpoint.opaque_payload
    blob_path = store._blob_path(
        payloads[0].checkpoint.ref.payload_sha256
    )

    def external_exact_create(path, payload, *, staging_dir=None):
        del payload, staging_dir
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(expected)
        raise FileExistsError("external exact CAS writer won")

    monkeypatch.setattr(
        store_module,
        "durable_publish_immutable_bytes",
        external_exact_create,
    )
    assert store.publish(checkpoint, payloads) == checkpoint
    assert blob_path.read_bytes() == expected


def test_checkpoint_blob_external_corrupt_create_race_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import noetrium_platform.research.experimentation.lifecycle.checkpoint.providers.directory_store as store_module

    store = DirectoryRunCheckpointStore(tmp_path / "blob-corrupt-race")
    payloads = (
        participant_payload("method", b"owned-content", generation="g1"),
    )
    checkpoint = manifest(payloads, checkpoint_id="blob-corrupt-race")
    blob_path = store._blob_path(
        payloads[0].checkpoint.ref.payload_sha256
    )
    foreign = b"foreign-corrupt-content"

    def external_corrupt_create(path, payload, *, staging_dir=None):
        del payload, staging_dir
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(foreign)
        raise FileExistsError("external corrupt CAS writer won")

    monkeypatch.setattr(
        store_module,
        "durable_publish_immutable_bytes",
        external_corrupt_create,
    )
    with pytest.raises(
        RunCheckpointIntegrityError,
        match="corrupt existing checkpoint blob",
    ):
        store.publish(checkpoint, payloads)

    assert blob_path.read_bytes() == foreign
    assert not store._manifest_path(checkpoint.checkpoint_id).exists()
    assert store._intents._path(checkpoint.checkpoint_id).exists()


def test_checkpoint_blob_retry_discards_hard_kill_staging_residue(
    tmp_path: Path,
) -> None:
    store = DirectoryRunCheckpointStore(tmp_path / "blob-hard-kill")
    payloads = (
        participant_payload("method", b"complete-owned-content", generation="g1"),
    )
    checkpoint = manifest(payloads, checkpoint_id="blob-hard-kill")
    digest = payloads[0].checkpoint.ref.payload_sha256
    blob_path = store._blob_path(digest)
    stranded = store.blob_staging / (
        f"{blob_path.name}.immutable.999999.simulated-hard-kill"
    )
    stranded.write_bytes(b"partial-crash-residue")

    assert not blob_path.exists()
    assert stranded.exists()
    assert store.publish(checkpoint, payloads) == checkpoint
    assert blob_path.read_bytes() == payloads[0].checkpoint.opaque_payload
    assert not stranded.exists()
    assert tuple(store.blob_staging.iterdir()) == ()


def test_checkpoint_gc_requires_complete_durable_carrier_closure(
    tmp_path: Path,
) -> None:
    store = DirectoryRunCheckpointStore(tmp_path / "gc-closure")
    payloads = (participant_payload("method", b"gc", generation="g1"),)
    owned = manifest(payloads, checkpoint_id="gc-closure")
    store.publish(owned, payloads)

    partial = store.assess_gc(
        owned.checkpoint_id,
        closures=(
            DurableCarrierReferenceClosure(
                DurableCarrierClosureAuthority.EXECUTION,
                "4" * 64,
                (),
            ),
        ),
    )
    assert not partial.closure_complete
    assert not partial.eligible
    with pytest.raises(RuntimeError, match="complete execution, evidence"):
        store.purge(owned.checkpoint_id, gc=partial)
    assert store.load(owned.checkpoint_id).manifest == owned


def test_checkpoint_gc_preserves_shared_cas_until_last_reference(
    tmp_path: Path,
) -> None:
    store = DirectoryRunCheckpointStore(tmp_path / "gc-shared")
    shared = participant_payload("method", b"shared-cas", generation="g1")
    first = manifest((shared,), checkpoint_id="shared-first")
    second = manifest((shared,), checkpoint_id="shared-second")
    store.publish(first, (shared,))
    store.publish(second, (shared,))

    digest = shared.checkpoint.ref.payload_sha256
    blob_path = store._blob_path(digest)
    assert blob_path.exists()

    assert store.purge(first.checkpoint_id, gc=closed_gc(store, first.checkpoint_id))
    assert blob_path.exists()
    assert store.load(second.checkpoint_id).participant_payloads == (shared,)

    assert store.purge(second.checkpoint_id, gc=closed_gc(store, second.checkpoint_id))
    assert not blob_path.exists()
    with pytest.raises(RunCheckpointConflict, match="retired"):
        store.publish(first, (shared,))


def test_pending_checkpoint_can_only_be_gc_after_recovery_closure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import noetrium_platform.research.experimentation.lifecycle.checkpoint.providers.directory_store as store_module

    store = DirectoryRunCheckpointStore(tmp_path / "gc-pending")
    payloads = (participant_payload("method", b"pending-owned", generation="g1"),)
    owned = manifest(payloads, checkpoint_id="pending-gc")
    real_atomic_replace = store_module.atomic_replace_bytes
    failed = False

    def fail_manifest_once(path, payload):
        nonlocal failed
        if path.parent == store.manifests and not failed:
            failed = True
            raise OSError("simulated manifest publication crash")
        return real_atomic_replace(path, payload)

    monkeypatch.setattr(store_module, "atomic_replace_bytes", fail_manifest_once)
    with pytest.raises(OSError, match="publication crash"):
        store.publish(owned, payloads)
    monkeypatch.setattr(store_module, "atomic_replace_bytes", real_atomic_replace)

    digest = payloads[0].checkpoint.ref.payload_sha256
    assert store._intents.load(owned.checkpoint_id) is not None
    assert store._blob_path(digest).exists()

    gc = closed_gc(store, owned.checkpoint_id)
    assert gc.persistence_state.value == "pending"
    assert gc.eligible
    assert store.purge(owned.checkpoint_id, gc=gc)
    assert store._intents.load(owned.checkpoint_id) is None
    assert not store._blob_path(digest).exists()
    with pytest.raises(RunCheckpointConflict, match="retired"):
        store.publish(owned, payloads)


def test_checkpoint_gc_retry_is_bound_to_original_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import noetrium_platform.research.experimentation.lifecycle.checkpoint.providers.directory_store as store_module

    store = DirectoryRunCheckpointStore(tmp_path / "gc-proof-retry")
    payloads = (participant_payload("method", b"retry-owned", generation="g1"),)
    owned = manifest(payloads, checkpoint_id="gc-proof-retry")
    store.publish(owned, payloads)
    original = closed_gc(store, owned.checkpoint_id)

    real_unlink = store_module.durable_unlink
    manifest_path = store._manifest_path(owned.checkpoint_id)
    failed = False

    def fail_manifest_unlink_once(path):
        nonlocal failed
        if path == manifest_path and not failed:
            failed = True
            raise OSError("simulated crash after retirement publication")
        return real_unlink(path)

    monkeypatch.setattr(store_module, "durable_unlink", fail_manifest_unlink_once)
    with pytest.raises(OSError, match="after retirement publication"):
        store.purge(owned.checkpoint_id, gc=original)

    monkeypatch.setattr(store_module, "durable_unlink", real_unlink)
    changed = store.assess_gc(
        owned.checkpoint_id,
        closures=(
            DurableCarrierReferenceClosure(
                DurableCarrierClosureAuthority.EVIDENCE,
                "a" * 64,
                (),
            ),
            DurableCarrierReferenceClosure(
                DurableCarrierClosureAuthority.EXECUTION,
                "b" * 64,
                (),
            ),
            DurableCarrierReferenceClosure(
                DurableCarrierClosureAuthority.RECOVERY,
                "c" * 64,
                (),
            ),
        ),
    )
    with pytest.raises(RuntimeError, match="GC proof changed"):
        store.purge(owned.checkpoint_id, gc=changed)

    assert store.purge(owned.checkpoint_id, gc=original)
    assert not manifest_path.exists()
