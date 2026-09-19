from __future__ import annotations

import json
import hashlib

import pytest

from noetrium_platform.research.experimentation.checkpoint.api import (
    RunCheckpointBundle,
    RunCheckpointIntegrityError,
    RunCheckpointManifest,
    RunParticipantPayload,
    RunParticipantSnapshotRef,
)
from noetrium_platform.research.experimentation.checkpoint.providers import DirectoryRunCheckpointStore
from noetrium_platform.research.experimentation.checkpoint.providers.codec import RunCheckpointManifestCodec
from noetrium_platform.capabilities.participant.core.api.checkpoint import ParticipantCheckpoint, ParticipantCheckpointRef


def _encoded() -> dict[str, object]:
    participant = ParticipantCheckpointRef(
        role="agent", runtime_binding_digest="binding-1",
        component_digest="component-1", session_id="session-1",
        payload_sha256="a" * 64,
    )
    manifest = RunCheckpointManifest(
        checkpoint_id="checkpoint-1", schema_version="4",
        experiment_spec_digest="spec-1", run_id="run-1", session_id="session-1",
        decision_cycle_id="cycle-1", cycle_identity_digest="cycle-digest-1",
        participant_snapshots=(RunParticipantSnapshotRef(participant, "generation-1"),),
    )
    return json.loads(RunCheckpointManifestCodec.encode(manifest))


def _decode(document: dict[str, object]) -> None:
    RunCheckpointManifestCodec.decode(
        json.dumps(document, separators=(",", ":")).encode("utf-8")
    )


def test_run_checkpoint_manifest_codec_round_trip() -> None:
    _decode(_encoded())


@pytest.mark.parametrize("mutation", ["envelope_extra", "manifest_extra", "digest_type"])
def test_run_checkpoint_manifest_codec_rejects_schema_drift(mutation: str) -> None:
    document = _encoded()
    if mutation == "envelope_extra":
        document["unexpected"] = True
    elif mutation == "manifest_extra":
        document["manifest"]["unexpected"] = True
    else:
        document["manifest_digest"] = 9
    with pytest.raises(RunCheckpointIntegrityError):
        _decode(document)


@pytest.mark.parametrize("field,value", [("generation", 1), ("generation", False)])
def test_run_checkpoint_manifest_codec_rejects_snapshot_type_drift(field, value) -> None:
    document = _encoded()
    document["manifest"]["participant_snapshots"][0][field] = value
    with pytest.raises(RunCheckpointIntegrityError):
        _decode(document)


@pytest.mark.parametrize(
    "field,value",
    [
        ("role", 1),
        ("runtime_binding_digest", False),
        ("payload_sha256", 7),
    ],
)
def test_run_checkpoint_manifest_codec_rejects_participant_ref_type_drift(
    field, value
) -> None:
    document = _encoded()
    document["manifest"]["participant_snapshots"][0]["checkpoint"][field] = value
    with pytest.raises(RunCheckpointIntegrityError):
        _decode(document)


def _bundle_fixture() -> tuple[RunCheckpointManifest, RunParticipantPayload]:
    payload = b"agent-state"
    checkpoint_ref = ParticipantCheckpointRef(
        role="agent", runtime_binding_digest="binding-1",
        component_digest="component-1", session_id="session-1",
        payload_sha256=hashlib.sha256(payload).hexdigest(),
    )
    snapshot = RunParticipantSnapshotRef(checkpoint_ref, "generation-1")
    manifest = RunCheckpointManifest(
        checkpoint_id="checkpoint-1", schema_version="4",
        experiment_spec_digest="spec-1", run_id="run-1", session_id="session-1",
        decision_cycle_id="cycle-1", cycle_identity_digest="cycle-digest-1",
        participant_snapshots=(snapshot,),
    )
    return manifest, RunParticipantPayload(snapshot, ParticipantCheckpoint(checkpoint_ref, payload))


def test_run_checkpoint_bundle_rejects_duplicate_payload_roles() -> None:
    manifest, payload = _bundle_fixture()
    with pytest.raises(ValueError, match="payload roles must be unique"):
        RunCheckpointBundle(manifest, (payload, payload))


def test_run_checkpoint_bundle_requires_exact_manifest_payload_set() -> None:
    manifest, _payload = _bundle_fixture()
    with pytest.raises(ValueError, match="payload roles must match the manifest"):
        RunCheckpointBundle(manifest, ())


def test_run_checkpoint_store_rejects_duplicate_payloads_before_blob_write(tmp_path) -> None:
    manifest, payload = _bundle_fixture()
    store = DirectoryRunCheckpointStore(tmp_path / "run-checkpoint-store")
    with pytest.raises(RunCheckpointIntegrityError):
        store.publish(manifest, (payload, payload))
    assert not any(store.blobs.rglob("*.bin"))


def test_run_participant_snapshot_ref_rejects_malformed_direct_values() -> None:
    checkpoint = ParticipantCheckpointRef(
        role="agent", runtime_binding_digest="binding-1",
        component_digest="component-1", session_id="session-1",
        payload_sha256="a" * 64,
    )
    with pytest.raises(ValueError, match="generation"):
        RunParticipantSnapshotRef(checkpoint, " ")
    with pytest.raises(ValueError, match="generation"):
        RunParticipantSnapshotRef(checkpoint, True)
    with pytest.raises(ValueError, match="ParticipantCheckpointRef"):
        RunParticipantSnapshotRef(object())


def test_run_checkpoint_manifest_rejects_mutable_or_untyped_snapshot_topology() -> None:
    manifest, payload = _bundle_fixture()
    values = dict(
        checkpoint_id=manifest.checkpoint_id, schema_version=manifest.schema_version,
        experiment_spec_digest=manifest.experiment_spec_digest, run_id=manifest.run_id,
        session_id=manifest.session_id, decision_cycle_id=manifest.decision_cycle_id,
        cycle_identity_digest=manifest.cycle_identity_digest,
    )
    with pytest.raises(ValueError, match="immutable tuple"):
        RunCheckpointManifest(**values, participant_snapshots=list(manifest.participant_snapshots))
    with pytest.raises(ValueError, match="RunParticipantSnapshotRef"):
        RunCheckpointManifest(**values, participant_snapshots=(object(),))


def test_run_checkpoint_bundle_rejects_mutable_or_untyped_payload_topology() -> None:
    manifest, payload = _bundle_fixture()
    with pytest.raises(ValueError, match="immutable typed tuple"):
        RunCheckpointBundle(manifest, [payload])
    with pytest.raises(ValueError, match="immutable typed tuple"):
        RunCheckpointBundle(manifest, (object(),))


def test_run_checkpoint_manifest_codec_rejects_empty_generation() -> None:
    document = _encoded()
    document["manifest"]["participant_snapshots"][0]["generation"] = " "
    document["manifest_digest"] = "ignored-because-contract-must-fail-first"
    with pytest.raises(RunCheckpointIntegrityError):
        _decode(document)
