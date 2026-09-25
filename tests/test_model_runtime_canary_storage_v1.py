from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import threading

import pytest

from noetrium_platform.capabilities.model.serving.api import RuntimeCanaryEvidence
from noetrium_platform.capabilities.model.serving.providers import (
    DirectoryRuntimeCanaryEvidenceStore,
    RuntimeCanaryEvidenceError,
)
from noetrium_platform.foundation.kernel.kernel.durability import encode_checksummed_document


def _digest(seed: str) -> str:
    return (seed * 64)[:64]


def _evidence() -> RuntimeCanaryEvidence:
    return RuntimeCanaryEvidence(
        deployment_id='deployment-1',
        deployment_generation=_digest('a'),
        route_digest=_digest('b'),
        role='planner',
        canary_id='planner-json',
        suite_digest=_digest('c'),
        process_pid=101,
        process_start_marker='start-a',
        argv_digest=_digest('d'),        request_digest=_digest('e'),
        probe_digest=_digest("0"),
        response_digest=_digest('f'),
        contract_digest=_digest('1'),
        passed=True,
        observed_at=10.0,
    )


def test_canary_store_round_trip_and_idempotent_replay(tmp_path: Path) -> None:
    store = DirectoryRuntimeCanaryEvidenceStore(tmp_path / 'canary')
    evidence = _evidence()
    manifest = _digest('2')
    first = store.publish(manifest, evidence)
    second = store.publish(manifest, evidence)
    assert first == second
    assert store.load(manifest, evidence.evidence_digest) == evidence


def test_canary_store_rejects_rechecksummed_type_corruption(tmp_path: Path) -> None:
    store = DirectoryRuntimeCanaryEvidenceStore(tmp_path / 'canary')
    evidence = _evidence()
    manifest = _digest('3')
    path = Path(store.publish(manifest, evidence))
    document = json.loads(path.read_text(encoding='utf-8'))
    document['payload']['evidence']['process_pid'] = True
    path.write_bytes(encode_checksummed_document('runtime-canary-evidence.v3', document['payload']))
    with pytest.raises(RuntimeCanaryEvidenceError):
        store.load(manifest, evidence.evidence_digest)



def test_canary_evidence_cannot_be_rebound_to_another_runtime_manifest(tmp_path: Path) -> None:
    store = DirectoryRuntimeCanaryEvidenceStore(tmp_path / 'canary')
    evidence = _evidence()
    source_manifest = _digest('5')
    target_manifest = _digest('6')
    source_path = Path(store.publish(source_manifest, evidence))
    target_path = store._path(target_manifest, evidence.evidence_digest)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(source_path.read_bytes())

    with pytest.raises(RuntimeCanaryEvidenceError, match='runtime manifest binding mismatch'):
        store.load(target_manifest, evidence.evidence_digest)

def test_canary_store_same_evidence_converges_across_instances(tmp_path: Path) -> None:
    root = tmp_path / 'canary'
    evidence = _evidence()
    manifest = _digest('4')
    barrier = threading.Barrier(8)
    paths: list[str] = []
    failures: list[BaseException] = []

    def publish() -> None:
        try:
            store = DirectoryRuntimeCanaryEvidenceStore(root)
            barrier.wait()
            paths.append(store.publish(manifest, evidence))
        except BaseException as exc:
            failures.append(exc)

    threads = [threading.Thread(target=publish) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(3.0)
    assert failures == []
    assert all(not thread.is_alive() for thread in threads)
    assert len(paths) == 8 and len(set(paths)) == 1


def test_canary_evidence_digest_changes_with_process_generation() -> None:
    evidence = _evidence()
    changed = replace(evidence, process_start_marker='start-b', evidence_digest='')
    assert changed.evidence_digest != evidence.evidence_digest
