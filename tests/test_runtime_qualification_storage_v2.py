from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import threading
import time

import pytest

from noetrium_platform.capabilities.model.serving.api import RuntimeQualificationReceipt, ServiceHeartbeat
from noetrium_platform.capabilities.model.serving.providers.runtime_qualification_storage import (
    DirectoryRuntimeQualificationEvidenceStore,
    RuntimeQualificationEvidenceError,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.kernel.durability import encode_checksummed_document


def _digest(seed: str) -> str:
    return (seed * 64)[:64]


def _receipt(deployment_id: str = "deployment-1") -> RuntimeQualificationReceipt:
    now = time.time()
    heartbeat = ServiceHeartbeat(
        deployment_id, _digest("a"), 123, "start-123", _digest("c"),
        True, _digest("b"), now - 0.1,
    )
    return RuntimeQualificationReceipt(
        deployment_id=deployment_id,
        stack_digest=_digest("a"),
        qualification_certificate_digest=_digest("b"),
        heartbeat_qualification_digest=_digest("b"),
        qualified_roles=("planner",),
        process_pid=heartbeat.pid,
        process_start_marker=heartbeat.process_start_marker,
        argv_digest=heartbeat.argv_digest,
        heartbeat_timestamp=float(heartbeat.timestamp),
        valid_until=now + 60.0,
        evidence_refs=(f"heartbeat:sha256:{canonical_digest(heartbeat)}",),
        created_at=now,
    )


def test_identical_replay_is_idempotent_and_conflict_is_rejected(tmp_path: Path) -> None:
    store = DirectoryRuntimeQualificationEvidenceStore(tmp_path / "qualification")
    receipt = _receipt()
    manifest = _digest("c")

    first = store.publish(manifest, receipt)
    second = store.publish(manifest, receipt)
    assert first == second
    assert store.load(manifest, receipt.deployment_id) == receipt

    conflict = replace(receipt, process_start_marker="other-start")
    with pytest.raises(RuntimeQualificationEvidenceError, match="different evidence"):
        store.publish(manifest, conflict)


def test_deployment_identity_cannot_escape_store_root(tmp_path: Path) -> None:
    root = tmp_path / "qualification"
    store = DirectoryRuntimeQualificationEvidenceStore(root)
    receipt = _receipt(r"..\..\outside")
    manifest = _digest("d")

    published = Path(store.publish(manifest, receipt)).resolve()
    assert published.parent == (root / manifest).resolve()
    assert published.name.endswith(".json")
    assert "outside" not in published.name
    assert store.load(manifest, receipt.deployment_id) == receipt


def test_valid_checksum_cannot_hide_receipt_type_corruption(tmp_path: Path) -> None:
    store = DirectoryRuntimeQualificationEvidenceStore(tmp_path / "qualification")
    receipt = _receipt()
    manifest = _digest("e")
    path = Path(store.publish(manifest, receipt))

    document = json.loads(path.read_text(encoding="utf-8"))
    payload = document["payload"]
    payload["receipt"]["created_at"] = "1.0"
    path.write_bytes(encode_checksummed_document("runtime-qualification-receipt.v4", payload))

    with pytest.raises(RuntimeQualificationEvidenceError):
        store.load(manifest, receipt.deployment_id)


def test_legacy_unchecksummed_receipt_is_rejected(tmp_path: Path) -> None:
    store = DirectoryRuntimeQualificationEvidenceStore(tmp_path / "qualification")
    receipt = _receipt()
    manifest = _digest("f")
    path = store._path(manifest, receipt.deployment_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"receipt": {"deployment_id": receipt.deployment_id}}), encoding="utf-8")

    with pytest.raises(RuntimeQualificationEvidenceError):
        store.load(manifest, receipt.deployment_id)



def test_receipt_cannot_be_rebound_to_another_runtime_manifest(tmp_path: Path) -> None:
    store = DirectoryRuntimeQualificationEvidenceStore(tmp_path / "qualification")
    receipt = _receipt()
    source_manifest = _digest("2")
    target_manifest = _digest("3")
    source_path = Path(store.publish(source_manifest, receipt))
    target_path = store._path(target_manifest, receipt.deployment_id)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(source_path.read_bytes())

    with pytest.raises(RuntimeQualificationEvidenceError, match="runtime manifest binding mismatch"):
        store.load(target_manifest, receipt.deployment_id)

def test_same_receipt_publish_is_single_domain_across_store_instances(tmp_path: Path) -> None:
    root = tmp_path / "qualification"
    receipt = _receipt()
    manifest = _digest("1")
    barrier = threading.Barrier(8)
    failures: list[BaseException] = []
    paths: list[str] = []

    def publish() -> None:
        try:
            store = DirectoryRuntimeQualificationEvidenceStore(root)
            barrier.wait()
            paths.append(store.publish(manifest, receipt))
        except BaseException as exc:
            failures.append(exc)

    threads = [threading.Thread(target=publish) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(3.0)

    assert all(not thread.is_alive() for thread in threads)
    assert failures == []
    assert len(paths) == 8 and len(set(paths)) == 1
    assert len(list((root / manifest).glob("*.json"))) == 1
