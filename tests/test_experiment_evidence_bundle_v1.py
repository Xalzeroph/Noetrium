from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

import pytest

from noetrium_platform.research.experimentation.run.api import (
    RunArtifactKind,
    RunArtifactSnapshotReceipt,
)
from noetrium_platform.research.experimentation.run.manifest.api import (
    DerivedEvidenceArtifact,
    EvidenceBundleManifest,
    EvidenceBundleReceipt,
    EvidenceBundleStatus,
    EvidenceStreamDescriptor,
)
from noetrium_platform.research.experimentation.run.manifest.runtime import (
    RunArtifactEvidenceBundlePublisher,
    decode_evidence_bundle_manifest,
    encode_evidence_bundle_manifest,
)
from noetrium_platform.research.experimentation.run.runtime import DirectoryRunArtifactStore

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64


class _InlineSerialActor:
    actor_id = "role03-evidence-test-inline-serial-actor"

    def call(self, operation, fn, /, *args, **kwargs):
        del operation, kwargs
        return fn(*args)


def _store(path: Path, *, run_id: str = "run-1") -> DirectoryRunArtifactStore:
    return DirectoryRunArtifactStore(path, run_id=run_id, writer_actor=_InlineSerialActor())


def _receipt(
    artifact_ref: str,
    *,
    generation: str,
    content_sha256: str,
    record_count: int,
    run_id: str = "run-1",
) -> RunArtifactSnapshotReceipt:
    return RunArtifactSnapshotReceipt(
        run_id=run_id,
        artifact_ref=artifact_ref,
        artifact_kind=RunArtifactKind.EVIDENCE,
        generation=generation,
        content_sha256=content_sha256,
        byte_size=max(1, record_count * 8),
        record_count=record_count,
    )


def _manifest(
    receipts: tuple[RunArtifactSnapshotReceipt, RunArtifactSnapshotReceipt] | None = None,
) -> EvidenceBundleManifest:
    if receipts is None:
        receipts = (
            _receipt("raw/environment.jsonl", generation=SHA_D, content_sha256=SHA_A, record_count=4),
            _receipt("raw/study.jsonl", generation=SHA_E, content_sha256=SHA_B, record_count=2),
        )
    return EvidenceBundleManifest(
        schema_version="2",
        bundle_id="episode-1",
        run_id="run-1",
        run_manifest_digest=SHA_C,
        status=EvidenceBundleStatus.COMPLETE,
        source_checkpoint_id="checkpoint-1",
        streams=(
            EvidenceStreamDescriptor(
                "environment-events", "environment.raw", "1", receipts[0], True, True,
            ),
            EvidenceStreamDescriptor(
                "study-events", "study.raw", "1", receipts[1], True, True,
            ),
        ),
        derived_artifacts=(
            DerivedEvidenceArtifact(
                "replay-overview", "replay_projection", "projections/replay.json",
                SHA_B, ("environment-events", "study-events"),
            ),
        ),
    )


def _finalize_rows(
    store: DirectoryRunArtifactStore,
    artifact_ref: str,
    rows: list[dict[str, int]],
) -> RunArtifactSnapshotReceipt:
    for row in rows:
        store.append_json(artifact_ref, row, kind=RunArtifactKind.EVIDENCE)
    return store.finalize(artifact_ref, kind=RunArtifactKind.EVIDENCE, record_stream=True)


def test_evidence_bundle_publishes_only_authority_finalized_streams(tmp_path: Path) -> None:
    store = _store(tmp_path / "run")
    environment = _finalize_rows(store, "raw/environment.jsonl", [{"n": n} for n in range(4)])
    study = _finalize_rows(store, "raw/study.jsonl", [{"n": n} for n in range(2)])
    manifest = _manifest((environment, study))

    receipt = RunArtifactEvidenceBundlePublisher(store).publish(manifest)
    target = tmp_path / "run" / "evidence" / "episode-1" / "manifest.json"
    assert receipt.run_manifest_digest == SHA_C
    assert receipt.manifest_ref == "evidence/episode-1/manifest.json"
    assert receipt.manifest_artifact_receipt.artifact_kind is RunArtifactKind.EVIDENCE
    assert receipt.manifest_artifact_receipt.record_count is None
    assert receipt.manifest_sha256 == manifest.digest
    assert receipt.manifest_sha256 == hashlib.sha256(target.read_bytes()).hexdigest()
    assert store.verify_finalized(receipt.manifest_artifact_receipt) == receipt.manifest_artifact_receipt
    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["schema_version"] == "2"
    assert [row["stream_id"] for row in document["streams"]] == [
        "environment-events",
        "study-events",
    ]
    assert document["streams"][0]["artifact_receipt"]["record_count"] == 4

def test_evidence_bundle_publication_replay_is_idempotent_after_manifest_seal(tmp_path: Path) -> None:
    store = _store(tmp_path / "run")
    environment = _finalize_rows(store, "raw/environment.jsonl", [{"n": 1}])
    study = _finalize_rows(store, "raw/study.jsonl", [{"n": 1}])
    manifest = _manifest((environment, study))
    publisher = RunArtifactEvidenceBundlePublisher(store)

    first = publisher.publish(manifest)
    second = publisher.publish(manifest)
    assert second == first
    assert store.verify_finalized(second.manifest_artifact_receipt) == second.manifest_artifact_receipt


def test_evidence_bundle_codec_round_trips_exact_v2_contract() -> None:
    manifest = _manifest()
    assert decode_evidence_bundle_manifest(encode_evidence_bundle_manifest(manifest)) == manifest


def test_evidence_bundle_rejects_old_schema_and_invalid_run_manifest_digest() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        EvidenceBundleManifest(**{**asdict(_manifest()), "schema_version": "1"})
    with pytest.raises(ValueError, match="run_manifest_digest"):
        EvidenceBundleManifest(**{**asdict(_manifest()), "run_manifest_digest": "not-a-sha"})
    with pytest.raises(ValueError, match="run_manifest_digest"):
        EvidenceBundleManifest(**{**asdict(_manifest()), "run_manifest_digest": "C" * 64})

def test_evidence_bundle_decoder_rejects_unknown_top_level_or_receipt_fields() -> None:
    document = json.loads(encode_evidence_bundle_manifest(_manifest()))
    document["undeclared"] = True
    with pytest.raises(ValueError, match="frozen manifest contract"):
        decode_evidence_bundle_manifest(json.dumps(document).encode())

    document = json.loads(encode_evidence_bundle_manifest(_manifest()))
    document["streams"][0]["artifact_receipt"]["undeclared"] = True
    with pytest.raises(ValueError, match="frozen manifest contract"):
        decode_evidence_bundle_manifest(json.dumps(document).encode())


def test_complete_evidence_bundle_rejects_empty_required_stream() -> None:
    stream = EvidenceStreamDescriptor(
        "environment-events",
        "environment.raw",
        "1",
        _receipt("raw/environment.jsonl", generation=SHA_D, content_sha256=SHA_A, record_count=0),
        True,
        True,
    )
    with pytest.raises(ValueError, match="empty required stream"):
        EvidenceBundleManifest(
            "2", "episode-1", "run-1", SHA_C, EvidenceBundleStatus.COMPLETE, None, (stream,)
        )


def test_derived_evidence_cannot_reference_absent_raw_stream() -> None:
    stream = EvidenceStreamDescriptor(
        "environment-events",
        "environment.raw",
        "1",
        _receipt("raw/environment.jsonl", generation=SHA_D, content_sha256=SHA_A, record_count=1),
        True,
        True,
    )
    artifact = DerivedEvidenceArtifact(
        "replay-overview", "projection", "projection.json", SHA_B, ("missing-stream",)
    )
    with pytest.raises(ValueError, match="missing streams"):
        EvidenceBundleManifest(
            "2", "episode-1", "run-1", SHA_C, EvidenceBundleStatus.COMPLETE,
            None, (stream,), (artifact,),
        )


def test_evidence_stream_requires_typed_record_stream_receipt() -> None:
    receipt = _receipt(
        "raw/environment.jsonl", generation=SHA_D, content_sha256=SHA_A, record_count=1
    )
    with pytest.raises(ValueError, match="typed run artifact"):
        EvidenceStreamDescriptor("environment-events", "environment.raw", "1", object(), True, True)
    with pytest.raises(ValueError, match="record_count"):
        EvidenceStreamDescriptor(
            "environment-events", "environment.raw", "1",
            replace(receipt, record_count=None), True, True,
        )


def test_evidence_bundle_rejects_receipt_run_identity_drift() -> None:
    first = _receipt(
        "raw/environment.jsonl", generation=SHA_D, content_sha256=SHA_A,
        record_count=1, run_id="run-2",
    )
    stream = EvidenceStreamDescriptor("environment-events", "environment.raw", "1", first, True, True)
    with pytest.raises(ValueError, match="different run"):
        EvidenceBundleManifest(
            "2", "episode-1", "run-1", SHA_C, EvidenceBundleStatus.COMPLETE, None, (stream,)
        )


def test_complete_publication_rejects_missing_required_source_stream(tmp_path: Path) -> None:
    store = _store(tmp_path / "run")
    missing = _receipt(
        "raw/DOES_NOT_EXIST.jsonl", generation=SHA_D, content_sha256=SHA_A, record_count=7
    )
    study = _receipt("raw/study.jsonl", generation=SHA_E, content_sha256=SHA_B, record_count=2)
    manifest = _manifest((missing, study))

    with pytest.raises(ValueError, match="not authority-finalized"):
        RunArtifactEvidenceBundlePublisher(store).publish(manifest)
    assert not (tmp_path / "run" / "raw" / "DOES_NOT_EXIST.jsonl").exists()
    assert not (tmp_path / "run" / "evidence" / "episode-1" / "manifest.json").exists()


def test_complete_publication_rejects_existing_but_unfinalized_stream(tmp_path: Path) -> None:
    store = _store(tmp_path / "run")
    store.publish_text("raw/environment.jsonl", '{"n":1}\n', kind=RunArtifactKind.EVIDENCE)
    target = tmp_path / "run" / "raw" / "environment.jsonl"
    unfinalized = RunArtifactSnapshotReceipt(
        run_id="run-1",
        artifact_ref="raw/environment.jsonl",
        artifact_kind=RunArtifactKind.EVIDENCE,
        generation=SHA_D,
        content_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        byte_size=target.stat().st_size,
        record_count=1,
    )
    second = _receipt("raw/study.jsonl", generation=SHA_E, content_sha256=SHA_B, record_count=2)
    with pytest.raises(ValueError, match="not authority-finalized"):
        RunArtifactEvidenceBundlePublisher(store).publish(_manifest((unfinalized, second)))


def test_complete_publication_rejects_digest_and_count_receipt_forgery(tmp_path: Path) -> None:
    store = _store(tmp_path / "run")
    environment = _finalize_rows(store, "raw/environment.jsonl", [{"n": 1}])
    study = _finalize_rows(store, "raw/study.jsonl", [{"n": 1}, {"n": 2}])
    publisher = RunArtifactEvidenceBundlePublisher(store)

    with pytest.raises(ValueError, match="not authority-finalized"):
        publisher.publish(_manifest((replace(environment, content_sha256=SHA_A), study)))
    with pytest.raises(ValueError, match="not authority-finalized"):
        publisher.publish(_manifest((replace(environment, record_count=7), study)))


def test_complete_publication_rejects_content_drift_but_accepts_portable_same_content_restore(tmp_path: Path) -> None:
    store = _store(tmp_path / "run")
    environment = _finalize_rows(store, "raw/environment.jsonl", [{"n": 1}])
    study = _finalize_rows(store, "raw/study.jsonl", [{"n": 1}, {"n": 2}])
    target = tmp_path / "run" / "raw" / "environment.jsonl"

    original = target.read_bytes()
    target.write_bytes(original + b'{"n":2}\n')
    with pytest.raises(ValueError, match="not authority-finalized"):
        RunArtifactEvidenceBundlePublisher(store).publish(_manifest((environment, study)))

    target.write_bytes(original)
    replacement = target.with_name("replacement.jsonl")
    replacement.write_bytes(target.read_bytes())
    replacement.replace(target)
    receipt = RunArtifactEvidenceBundlePublisher(store).publish(_manifest((environment, study)))
    assert receipt.manifest_sha256 == _manifest((environment, study)).digest

def test_complete_publication_rejects_publisher_store_run_mismatch(tmp_path: Path) -> None:
    source = _store(tmp_path / "run-1", run_id="run-1")
    environment = _finalize_rows(source, "raw/environment.jsonl", [{"n": 1}])
    study = _finalize_rows(source, "raw/study.jsonl", [{"n": 1}])
    wrong_store = _store(tmp_path / "run-2", run_id="run-2")

    with pytest.raises(ValueError, match="not authority-finalized"):
        RunArtifactEvidenceBundlePublisher(wrong_store).publish(_manifest((environment, study)))


def test_evidence_bundle_requires_typed_status() -> None:
    stream = EvidenceStreamDescriptor(
        "environment-events", "environment.raw", "1",
        _receipt("raw/environment.jsonl", generation=SHA_D, content_sha256=SHA_A, record_count=1),
        True, True,
    )
    with pytest.raises(ValueError, match="EvidenceBundleStatus"):
        EvidenceBundleManifest("2", "episode-1", "run-1", SHA_C, "complete", None, (stream,))


def test_evidence_bundle_receipt_preserves_typed_finalized_manifest_identity() -> None:
    manifest_artifact = RunArtifactSnapshotReceipt(
        run_id="run-1",
        artifact_ref="evidence/episode-1/manifest.json",
        artifact_kind=RunArtifactKind.EVIDENCE,
        generation=SHA_D,
        content_sha256=SHA_A,
        byte_size=42,
        record_count=None,
    )
    valid = dict(
        bundle_id="episode-1",
        run_id="run-1",
        run_manifest_digest=SHA_C,
        manifest_artifact_receipt=manifest_artifact,
    )
    receipt = EvidenceBundleReceipt(**valid)
    assert receipt.manifest_ref == "evidence/episode-1/manifest.json"
    assert receipt.manifest_sha256 == SHA_A
    assert receipt.manifest_artifact_receipt is manifest_artifact
    assert len(receipt.digest) == 64
    same_receipt = EvidenceBundleReceipt(**valid)
    assert receipt.digest == same_receipt.digest
    with pytest.raises(ValueError):
        EvidenceBundleReceipt(**{**valid, "bundle_id": "../escape"})
    with pytest.raises(ValueError):
        EvidenceBundleReceipt(**{**valid, "run_id": " "})
    with pytest.raises(ValueError):
        EvidenceBundleReceipt(**{**valid, "run_manifest_digest": "not-a-sha"})
    with pytest.raises(ValueError):
        EvidenceBundleReceipt(**{**valid, "run_manifest_digest": "C" * 64})
    with pytest.raises(ValueError, match="different run"):
        EvidenceBundleReceipt(**{**valid, "run_id": "run-2"})
    with pytest.raises(ValueError, match="artifact ref"):
        EvidenceBundleReceipt(**{
            **valid,
            "manifest_artifact_receipt": replace(
                manifest_artifact, artifact_ref="evidence/other/manifest.json"
            ),
        })
    with pytest.raises(ValueError, match="invalid semantics"):
        EvidenceBundleReceipt(**{
            **valid,
            "manifest_artifact_receipt": replace(manifest_artifact, record_count=1),
        })
    with pytest.raises(ValueError, match="typed finalized"):
        EvidenceBundleReceipt(**{**valid, "manifest_artifact_receipt": object()})
