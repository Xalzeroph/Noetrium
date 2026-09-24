from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import replace
import hashlib
import json
import threading

import pytest

from noetrium_platform.research.experimentation.lifecycle.api import (
    RunCheckpointConflict,
    RunCheckpointIntegrityError,
    RunCheckpointRecoveryRequired,
    WorkloadCheckpointBundle,
    WorkloadCheckpointComponentRef,
    WorkloadCheckpointPayload,
    WorkloadExecutionCut,
    build_workload_checkpoint_manifest,
)
from noetrium_platform.research.experimentation.lifecycle.checkpoint.providers import DirectoryWorkloadCheckpointStore
from noetrium_platform.research.experimentation.lifecycle.checkpoint.providers.workload_codec import (
    WorkloadCheckpointManifestCodec,
)


def _encoded() -> dict[str, object]:
    ref = WorkloadCheckpointComponentRef(
        "component-1", "codec-1", "1", "a" * 64, 4
    )
    manifest = build_workload_checkpoint_manifest(
        run_id="run-1", study_id="study-1", workload_id="workload-1",
        branch_id="branch-1", source_cut_id="cut-1",
        environment_generation="env-1", method_generation="method-1",
        task_manifest_digest="tasks-1",
        checkpoint_compatibility_digest="a" * 64,
        execution_cut=WorkloadExecutionCut(("task-1",)), component_refs=(ref,),
    )
    return json.loads(WorkloadCheckpointManifestCodec.encode(manifest))


def _decode(document: dict[str, object]) -> None:
    WorkloadCheckpointManifestCodec.decode(
        json.dumps(document, separators=(",", ":")).encode("utf-8")
    )


def test_workload_checkpoint_manifest_codec_round_trip() -> None:
    _decode(_encoded())


@pytest.mark.parametrize("mutation", ["envelope_extra", "manifest_extra", "digest_type"])
def test_workload_checkpoint_manifest_codec_rejects_schema_drift(mutation: str) -> None:
    document = _encoded()
    if mutation == "envelope_extra":
        document["unexpected"] = True
    elif mutation == "manifest_extra":
        document["manifest"]["unexpected"] = True
    else:
        document["manifest_digest"] = 7
    with pytest.raises(RunCheckpointIntegrityError):
        _decode(document)


@pytest.mark.parametrize("field,value", [("payload_size", True), ("codec_id", 7)])
def test_workload_checkpoint_manifest_codec_rejects_component_type_drift(field, value) -> None:
    document = _encoded()
    document["manifest"]["component_refs"][0][field] = value
    with pytest.raises(RunCheckpointIntegrityError):
        _decode(document)


@pytest.mark.parametrize(
    "field,value",
    [
        ("completed_task_ids", "task-1"),
        ("current_task_id", 1),
        ("decision_cycle_id", False),
        ("status", 1),
    ],
)
def test_workload_checkpoint_manifest_codec_rejects_execution_cut_type_drift(
    field, value
) -> None:
    document = _encoded()
    document["manifest"]["execution_cut"][field] = value
    with pytest.raises(RunCheckpointIntegrityError):
        _decode(document)


def _direct_manifest_and_payload():
    payload = b"data"
    ref = WorkloadCheckpointComponentRef(
        "component-1", "codec-1", "1", hashlib.sha256(payload).hexdigest(), len(payload)
    )
    manifest = build_workload_checkpoint_manifest(
        run_id="run-1", study_id="study-1", workload_id="workload-1",
        branch_id="branch-1", source_cut_id="cut-1", environment_generation="env-1",
        method_generation="method-1", task_manifest_digest="tasks-1", checkpoint_compatibility_digest="a" * 64,
        execution_cut=WorkloadExecutionCut(("task-1",)), component_refs=(ref,),
    )
    return manifest, WorkloadCheckpointPayload(ref, payload)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: WorkloadExecutionCut(["task-1"]),
        lambda: WorkloadExecutionCut(("task-1",), current_task_id=False),
        lambda: WorkloadCheckpointComponentRef("component-1", "codec-1", "1", "a" * 64, True),
        lambda: WorkloadCheckpointPayload(
            WorkloadCheckpointComponentRef("component-1", "codec-1", "1", hashlib.sha256(b"x").hexdigest(), 1),
            bytearray(b"x"),
        ),
    ],
)
def test_workload_checkpoint_direct_contracts_reject_type_drift(factory) -> None:
    with pytest.raises((TypeError, ValueError)):
        factory()


def test_workload_checkpoint_bundle_rejects_duplicate_payload_components() -> None:
    manifest, payload = _direct_manifest_and_payload()
    with pytest.raises(ValueError, match="payload component ids must be unique"):
        WorkloadCheckpointBundle(manifest, (payload, payload))


def test_workload_checkpoint_store_rejects_duplicate_payloads_before_blob_write(tmp_path) -> None:
    manifest, payload = _direct_manifest_and_payload()
    store = DirectoryWorkloadCheckpointStore(tmp_path / "checkpoint-store")
    with pytest.raises(RunCheckpointIntegrityError):
        store.publish(manifest, (payload, payload))
    assert not any(store._content.blobs.rglob("*.bin"))



def test_workload_checkpoint_publish_fences_conflicting_concurrent_writers(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import noetrium_platform.research.experimentation.lifecycle.checkpoint.providers.workload_store as store_module

    root = tmp_path / "workload-checkpoint-race"
    first_store = DirectoryWorkloadCheckpointStore(root)
    second_store = DirectoryWorkloadCheckpointStore(root)

    first_manifest, first_payload = _direct_manifest_and_payload()

    other_bytes = b"other"
    other_ref = WorkloadCheckpointComponentRef(
        "component-1",
        "codec-1",
        "1",
        hashlib.sha256(other_bytes).hexdigest(),
        len(other_bytes),
    )
    other_payload = WorkloadCheckpointPayload(other_ref, other_bytes)
    other_manifest = build_workload_checkpoint_manifest(
        run_id="run-1",
        study_id="study-1",
        workload_id="workload-1",
        branch_id="branch-1",
        source_cut_id="cut-1",
        environment_generation="env-1",
        method_generation="method-1",
        task_manifest_digest="tasks-1",
        checkpoint_compatibility_digest="a" * 64,
        execution_cut=WorkloadExecutionCut(("task-2",)),
        component_refs=(other_ref,),
    )
    other_manifest = replace(
        other_manifest,
        checkpoint_id=first_manifest.checkpoint_id,
    )

    real_atomic_replace = store_module.atomic_replace_bytes
    first_manifest_write_entered = threading.Event()
    allow_first_manifest_write = threading.Event()
    manifest_write_count = 0
    manifest_write_lock = threading.Lock()

    def gate_first_manifest_write(path, payload):
        nonlocal manifest_write_count
        if path.parent == first_store._manifests:
            with manifest_write_lock:
                manifest_write_count += 1
                ordinal = manifest_write_count
            if ordinal == 1:
                first_manifest_write_entered.set()
                if not allow_first_manifest_write.wait(timeout=5.0):
                    raise TimeoutError("test did not release first workload manifest writer")
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
            (first_payload,),
        )
        assert first_manifest_write_entered.wait(timeout=5.0)
        second_future = executor.submit(
            second_store.publish,
            other_manifest,
            (other_payload,),
        )

        with pytest.raises(FutureTimeoutError):
            second_future.result(timeout=0.2)

        allow_first_manifest_write.set()
        assert first_future.result(timeout=5.0) == first_manifest
        with pytest.raises(RunCheckpointConflict):
            second_future.result(timeout=5.0)

    loaded = DirectoryWorkloadCheckpointStore(root).load(
        first_manifest.checkpoint_id
    )
    assert loaded.manifest == first_manifest
    assert loaded.payloads == (first_payload,)
    losing_blob = second_store._content._blob_path(other_ref.payload_sha256)
    assert not losing_blob.exists()



def test_workload_checkpoint_publish_intent_recovers_manifest_crash(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import noetrium_platform.research.experimentation.lifecycle.checkpoint.providers.workload_store as store_module

    root = tmp_path / "workload-intent-crash"
    store = DirectoryWorkloadCheckpointStore(root)
    owned_manifest, owned_payload = _direct_manifest_and_payload()

    real_atomic_replace = store_module.atomic_replace_bytes
    failed = False

    def fail_manifest_once(path, payload):
        nonlocal failed
        if path.parent == store._manifests and not failed:
            failed = True
            raise OSError("simulated workload manifest crash")
        return real_atomic_replace(path, payload)

    monkeypatch.setattr(
        store_module,
        "atomic_replace_bytes",
        fail_manifest_once,
    )
    with pytest.raises(OSError, match="workload manifest crash"):
        store.publish(owned_manifest, (owned_payload,))

    intent_path = store._intents._path(owned_manifest.checkpoint_id)
    assert intent_path.exists()
    assert not store._manifest_path(owned_manifest.checkpoint_id).exists()
    assert store._content._blob_path(
        owned_payload.ref.payload_sha256
    ).exists()

    pending = DirectoryWorkloadCheckpointStore(root)
    with pytest.raises(RunCheckpointRecoveryRequired) as raised:
        pending.load(owned_manifest.checkpoint_id)
    recovery = raised.value
    assert recovery.checkpoint_id == owned_manifest.checkpoint_id
    assert recovery.namespace == "workload"
    assert recovery.manifest_sha256 == pending._intents.load(
        owned_manifest.checkpoint_id
    ).manifest_sha256
    assert recovery.blob_sha256s == (owned_payload.ref.payload_sha256,)

    other_bytes = b"conflict"
    other_ref = WorkloadCheckpointComponentRef(
        "component-1",
        "codec-1",
        "1",
        hashlib.sha256(other_bytes).hexdigest(),
        len(other_bytes),
    )
    other_payload = WorkloadCheckpointPayload(other_ref, other_bytes)
    other_manifest = build_workload_checkpoint_manifest(
        run_id="run-1",
        study_id="study-1",
        workload_id="workload-1",
        branch_id="branch-1",
        source_cut_id="cut-1",
        environment_generation="env-1",
        method_generation="method-1",
        task_manifest_digest="tasks-1",
        checkpoint_compatibility_digest="a" * 64,
        execution_cut=WorkloadExecutionCut(("task-9",)),
        component_refs=(other_ref,),
    )
    other_manifest = replace(
        other_manifest,
        checkpoint_id=owned_manifest.checkpoint_id,
    )

    with pytest.raises(RunCheckpointConflict):
        DirectoryWorkloadCheckpointStore(root).publish(
            other_manifest,
            (other_payload,),
        )
    assert not store._content._blob_path(other_ref.payload_sha256).exists()

    monkeypatch.setattr(
        store_module,
        "atomic_replace_bytes",
        real_atomic_replace,
    )
    reopened = DirectoryWorkloadCheckpointStore(root)
    assert reopened.publish(
        owned_manifest,
        (owned_payload,),
    ) == owned_manifest
    assert not reopened._intents._path(
        owned_manifest.checkpoint_id
    ).exists()
    assert reopened.load(owned_manifest.checkpoint_id).manifest == owned_manifest
