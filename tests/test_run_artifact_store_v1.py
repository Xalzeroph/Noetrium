from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from noetrium_platform.research.experimentation.run.api import (
    RunArtifactFinalizationError,
    RunArtifactKind,
    RunArtifactSealedError,
    RunArtifactSnapshotReceipt,
    RunArtifactVerificationError,
)
from noetrium_platform.research.experimentation.run.runtime import DirectoryRunArtifactStore


class _InlineSerialActor:
    actor_id = "role03-test-inline-serial-actor"

    def call(self, operation, fn, /, *args, **kwargs):
        del operation, kwargs
        return fn(*args)


def _store(path: Path, *, run_id: str = "run-1") -> DirectoryRunArtifactStore:
    return DirectoryRunArtifactStore(path, run_id=run_id, writer_actor=_InlineSerialActor())


def test_directory_run_artifact_store_publishes_atomic_json(tmp_path: Path) -> None:
    store = _store(tmp_path / "run")
    path = store.publish_json(
        "nested/result.json",
        {"status": "ok", "value": 3},
        kind=RunArtifactKind.RESULT,
    )
    assert json.loads((tmp_path / "run" / "nested" / "result.json").read_text()) == {
        "status": "ok",
        "value": 3,
    }
    assert path.endswith("nested\\result.json") or path.endswith("nested/result.json")


def test_directory_run_artifact_store_rejects_escape_and_reserved_authority_path(tmp_path: Path) -> None:
    store = _store(tmp_path / "run")
    with pytest.raises(ValueError):
        store.path("../outside.json", kind=RunArtifactKind.RESULT)
    with pytest.raises(ValueError, match="reserved authority path"):
        store.path(".run-artifact-finalized/forged.json", kind=RunArtifactKind.EVIDENCE)


def test_directory_run_artifact_store_publishes_text_atomically(tmp_path: Path) -> None:
    store = _store(tmp_path / "run")
    path = store.publish_text(
        "evidence/j_eval.jsonl",
        '{"eval_id":"one"}\n',
        kind=RunArtifactKind.EVIDENCE,
    )
    assert (tmp_path / "run" / "evidence" / "j_eval.jsonl").read_text() == '{"eval_id":"one"}\n'
    assert path.endswith("j_eval.jsonl")


def test_finalize_record_stream_issues_authoritative_receipt_and_verifies(tmp_path: Path) -> None:
    store = _store(tmp_path / "run")
    store.append_json("raw/events.jsonl", {"n": 1}, kind=RunArtifactKind.EVIDENCE)
    store.append_json("raw/events.jsonl", {"n": 2}, kind=RunArtifactKind.EVIDENCE)

    receipt = store.finalize(
        "raw/events.jsonl",
        kind=RunArtifactKind.EVIDENCE,
        record_stream=True,
    )
    target = tmp_path / "run" / "raw" / "events.jsonl"
    assert receipt.run_id == "run-1"
    assert receipt.artifact_ref == "raw/events.jsonl"
    assert receipt.artifact_kind is RunArtifactKind.EVIDENCE
    assert receipt.record_count == 2
    assert receipt.byte_size == target.stat().st_size
    assert receipt.content_sha256 == hashlib.sha256(target.read_bytes()).hexdigest()
    assert store.verify_finalized(receipt) == receipt


def test_finalize_missing_artifact_fails_closed(tmp_path: Path) -> None:
    store = _store(tmp_path / "run")
    with pytest.raises(RunArtifactFinalizationError, match="missing"):
        store.finalize("raw/missing.jsonl", kind=RunArtifactKind.EVIDENCE, record_stream=True)


def test_verify_rejects_existing_but_unfinalized_artifact(tmp_path: Path) -> None:
    store = _store(tmp_path / "run")
    store.publish_text("raw/events.jsonl", '{"n":1}\n', kind=RunArtifactKind.EVIDENCE)
    target = tmp_path / "run" / "raw" / "events.jsonl"
    forged = RunArtifactSnapshotReceipt(
        run_id="run-1",
        artifact_ref="raw/events.jsonl",
        artifact_kind=RunArtifactKind.EVIDENCE,
        generation="a" * 64,
        content_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        byte_size=target.stat().st_size,
        record_count=1,
    )
    with pytest.raises(RunArtifactVerificationError, match="seal is missing"):
        store.verify_finalized(forged)

def test_verify_rejects_digest_or_count_receipt_forgery(tmp_path: Path) -> None:
    store = _store(tmp_path / "run")
    store.append_json("raw/events.jsonl", {"n": 1}, kind=RunArtifactKind.EVIDENCE)
    receipt = store.finalize("raw/events.jsonl", kind=RunArtifactKind.EVIDENCE, record_stream=True)

    with pytest.raises(RunArtifactVerificationError, match="seal does not match"):
        store.verify_finalized(replace(receipt, content_sha256="b" * 64))
    with pytest.raises(RunArtifactVerificationError, match="seal does not match"):
        store.verify_finalized(replace(receipt, record_count=receipt.record_count + 1))

def test_verify_rejects_content_drift_after_finalization(tmp_path: Path) -> None:
    store = _store(tmp_path / "run")
    store.append_json("raw/events.jsonl", {"n": 1}, kind=RunArtifactKind.EVIDENCE)
    receipt = store.finalize("raw/events.jsonl", kind=RunArtifactKind.EVIDENCE, record_stream=True)
    target = tmp_path / "run" / "raw" / "events.jsonl"
    target.write_bytes(target.read_bytes() + b'{"n":2}\n')

    with pytest.raises(RunArtifactVerificationError, match="content drifted"):
        store.verify_finalized(receipt)

def test_verify_accepts_portable_same_content_restore(tmp_path: Path) -> None:
    source_root = tmp_path / "run"
    store = _store(source_root)
    store.publish_text("raw/events.jsonl", '{"n":1}\n', kind=RunArtifactKind.EVIDENCE)
    receipt = store.finalize("raw/events.jsonl", kind=RunArtifactKind.EVIDENCE, record_stream=True)

    restored_root = tmp_path / "restored-run"
    shutil.copytree(source_root, restored_root)
    restored = _store(restored_root)
    assert restored.verify_finalized(receipt) == receipt

    target = restored_root / "raw" / "events.jsonl"
    replacement = target.with_name("replacement.jsonl")
    replacement.write_bytes(target.read_bytes())
    replacement.replace(target)
    assert restored.verify_finalized(receipt) == receipt

def test_finalization_seals_writes_across_reopen(tmp_path: Path) -> None:
    root = tmp_path / "run"
    store = _store(root)
    store.append_json("raw/events.jsonl", {"n": 1}, kind=RunArtifactKind.EVIDENCE)
    receipt = store.finalize("raw/events.jsonl", kind=RunArtifactKind.EVIDENCE, record_stream=True)

    with pytest.raises(RunArtifactSealedError, match="finalized and sealed"):
        store.append_json("raw/events.jsonl", {"n": 2}, kind=RunArtifactKind.EVIDENCE)
    with pytest.raises(RunArtifactSealedError, match="finalized and sealed"):
        store.publish_text("raw/events.jsonl", '{"n":2}\n', kind=RunArtifactKind.EVIDENCE)

    reopened = _store(root)
    assert reopened.verify_finalized(receipt) == receipt
    assert reopened.finalize("raw/events.jsonl", kind=RunArtifactKind.EVIDENCE, record_stream=True) == receipt
    with pytest.raises(RunArtifactSealedError, match="finalized and sealed"):
        reopened.append_json("raw/events.jsonl", {"n": 3}, kind=RunArtifactKind.EVIDENCE)


def test_finalize_failure_before_seal_commit_leaves_artifact_writable(tmp_path: Path, monkeypatch) -> None:
    import noetrium_platform.research.experimentation.run.runtime.artifacts as artifacts_runtime

    root = tmp_path / "run"
    store = _store(root)
    store.append_json("raw/events.jsonl", {"n": 1}, kind=RunArtifactKind.EVIDENCE)

    def fail_seal(path: Path, payload: bytes) -> None:
        del path, payload
        raise OSError("injected seal publication failure")

    monkeypatch.setattr(artifacts_runtime, "atomic_replace_bytes", fail_seal)
    with pytest.raises(OSError, match="seal publication failure"):
        store.finalize("raw/events.jsonl", kind=RunArtifactKind.EVIDENCE, record_stream=True)

    authority = root / ".run-artifact-finalized"
    assert not (authority / "seals").exists()
    assert not (authority / "generations").exists()
    store.append_json("raw/events.jsonl", {"n": 2}, kind=RunArtifactKind.EVIDENCE)


def test_finalize_failure_after_seal_commit_blocks_writes_and_recovers(tmp_path: Path, monkeypatch) -> None:
    import noetrium_platform.research.experimentation.run.runtime.artifacts as artifacts_runtime
    from noetrium_platform.foundation.kernel.kernel.durability import atomic_replace_bytes as durable_atomic_replace

    root = tmp_path / "run"
    store = _store(root)
    store.append_json("raw/events.jsonl", {"n": 1}, kind=RunArtifactKind.EVIDENCE)
    calls = 0

    def fail_index(path: Path, payload: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            durable_atomic_replace(path, payload)
            return
        raise OSError("injected generation index failure")

    monkeypatch.setattr(artifacts_runtime, "atomic_replace_bytes", fail_index)
    with pytest.raises(OSError, match="generation index failure"):
        store.finalize("raw/events.jsonl", kind=RunArtifactKind.EVIDENCE, record_stream=True)

    authority = root / ".run-artifact-finalized"
    assert len(list((authority / "seals").glob("*.json"))) == 1
    assert not (authority / "generations").exists()
    with pytest.raises(RunArtifactSealedError):
        store.append_json("raw/events.jsonl", {"n": 2}, kind=RunArtifactKind.EVIDENCE)
    with pytest.raises(RunArtifactSealedError):
        store.publish_text("raw/events.jsonl", '{"n":2}\n', kind=RunArtifactKind.EVIDENCE)

    monkeypatch.setattr(artifacts_runtime, "atomic_replace_bytes", durable_atomic_replace)
    reopened = _store(root)
    receipt = reopened.finalize("raw/events.jsonl", kind=RunArtifactKind.EVIDENCE, record_stream=True)
    assert len(list((authority / "generations").glob("*.json"))) == 1
    assert reopened.verify_finalized(receipt) == receipt


def test_reopen_repairs_missing_or_corrupt_generation_index_from_seal(tmp_path: Path) -> None:
    root = tmp_path / "run"
    store = _store(root)
    store.append_json("raw/events.jsonl", {"n": 1}, kind=RunArtifactKind.EVIDENCE)
    receipt = store.finalize("raw/events.jsonl", kind=RunArtifactKind.EVIDENCE, record_stream=True)
    ledger = root / ".run-artifact-finalized" / "generations" / f"{receipt.generation}.json"

    ledger.unlink()
    assert store.verify_finalized(receipt) == receipt
    reopened = _store(root)
    assert reopened.finalize("raw/events.jsonl", kind=RunArtifactKind.EVIDENCE, record_stream=True) == receipt
    assert ledger.is_file()

    ledger.write_bytes(b"{}")
    with pytest.raises(RunArtifactVerificationError, match="generation ledger does not match"):
        reopened.verify_finalized(receipt)
    repaired = _store(root)
    assert repaired.finalize("raw/events.jsonl", kind=RunArtifactKind.EVIDENCE, record_stream=True) == receipt
    assert repaired.verify_finalized(receipt) == receipt


def test_snapshot_receipt_requires_canonical_lowercase_sha256(tmp_path: Path) -> None:
    store = _store(tmp_path / "run")
    store.publish_text("raw/events.jsonl", '{"n":1}\n', kind=RunArtifactKind.EVIDENCE)
    receipt = store.finalize("raw/events.jsonl", kind=RunArtifactKind.EVIDENCE, record_stream=True)
    with pytest.raises(ValueError, match="generation must be SHA-256"):
        replace(receipt, generation="A" * 64)
    with pytest.raises(ValueError, match="content_sha256 must be SHA-256"):
        replace(receipt, content_sha256="B" * 64)


def test_finalize_uses_platform_atomic_replace_for_ledger_and_seal(tmp_path: Path, monkeypatch) -> None:
    import noetrium_platform.research.experimentation.run.runtime.artifacts as artifacts_runtime
    from noetrium_platform.foundation.kernel.kernel.durability import atomic_replace_bytes as platform_atomic_replace_bytes

    calls: list[Path] = []
    def spy(path: Path, payload: bytes) -> None:
        calls.append(path)
        platform_atomic_replace_bytes(path, payload)

    store = _store(tmp_path / "run")
    store.publish_text("raw/events.jsonl", '{"n":1}\n', kind=RunArtifactKind.EVIDENCE)
    monkeypatch.setattr(artifacts_runtime, "atomic_replace_bytes", spy)
    store.finalize("raw/events.jsonl", kind=RunArtifactKind.EVIDENCE, record_stream=True)
    assert len(calls) == 2
    assert "seals" in calls[0].parts
    assert "generations" in calls[1].parts


def test_verify_rejects_receipt_from_another_run(tmp_path: Path) -> None:
    store = _store(tmp_path / "run", run_id="run-1")
    other = _store(tmp_path / "other", run_id="run-2")
    other.publish_text("raw/events.jsonl", '{"n":1}\n', kind=RunArtifactKind.EVIDENCE)
    receipt = other.finalize("raw/events.jsonl", kind=RunArtifactKind.EVIDENCE, record_stream=True)

    with pytest.raises(RunArtifactVerificationError, match="different run"):
        store.verify_finalized(receipt)
