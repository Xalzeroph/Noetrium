from pathlib import Path
import hashlib
import tempfile

import pytest

from noetrium_platform.foundation.kernel.kernel import ComponentIdentity
from noetrium_platform.capabilities.participant.core.api.checkpoint import ParticipantCheckpoint
from noetrium_platform.capabilities.participant.core.api.contracts import ParticipantImplementationIdentity, ParticipantRuntimeBinding
from noetrium_platform.research.experimentation.checkpoint.api.contracts import (
    RunCheckpointConflict,
    RunCheckpointManifest,
    RunParticipantPayload,
    RunParticipantSnapshotRef,
)
from noetrium_platform.research.experimentation.checkpoint.providers.directory_store import DirectoryRunCheckpointStore
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
