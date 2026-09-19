from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import threading
import time

import pytest

from noetrium_platform.capabilities.model.serving.api import (
    DeploymentPlacement,
    QualificationCertificate,
    QualifiedDeploymentManifest,
    ResourceEnvelope,
    RoleModelAssignment,
    RoleModelManifest,
    RuntimeCanaryEvidence,
    RuntimeQualificationReceipt,
    ServiceHeartbeat,
    build_runtime_qualification_receipt,
)
from noetrium_platform.capabilities.model.serving.composition import publish_qualified_model_deployment_closure
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointRoute,
    QualifiedModelClosurePublication,
)
from noetrium_platform.capabilities.model.serving.endpoint.providers import (
    PersistedQualifiedModelEndpointBinding,
    QualifiedModelClosurePublicationError,
    QualifiedModelClosureReadError,
    load_qualified_model_deployment_closure,
    publish_qualified_model_deployment_closure as _publish_with_store,
)
from noetrium_platform.capabilities.model.serving.providers import (
    DirectoryRuntimeCanaryEvidenceStore,
    DirectoryRuntimeQualificationEvidenceStore,
)
from noetrium_platform.capabilities.model.stack.api import ModelArtifactClosure, ModelStackSpec, RuntimeBuildIdentity
from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity, canonical_digest
from noetrium_platform.foundation.kernel.kernel.durability import (
    decode_checksummed_document,
    encode_checksummed_document,
)


def _digest(seed: str) -> str:
    return (seed * 64)[:64]


def _publication() -> QualifiedModelClosurePublication:
    identity = ImmutableModelIdentity(
        "planner-model", "repo/model", "revision", "vllm", "0.1",
        "bfloat16", None, 8192,
    )
    stack = ModelStackSpec(
        identity,
        ModelArtifactClosure(
            _digest("a"), _digest("b"), _digest("c"), _digest("d"), _digest("e")
        ),
        RuntimeBuildIdentity(
            _digest("f"), _digest("1"), _digest("2"),
            "cuda-12.8", "nccl-2.27", "torch-2.8", _digest("3"),
        ),
        1, 1, 1, 1,
        None, None, None, None, "fcfs", (),
    )
    certificate = QualificationCertificate(
        stack.digest(), _digest("4"), ("planner",),
        ResourceEnvelope(70 << 30, 100 << 30, 2, 1.0, 0.1, 100.0),
        _digest("5"),
    )
    deployment = QualifiedDeploymentManifest(
        "deployment-1", stack, certificate, DeploymentPlacement(("GPU-1",)), _digest("5")
    )
    route = ModelEndpointRoute(
        deployment.deployment_id,
        deployment.digest(),
        "http://127.0.0.1:30000",
        timeout_s=17.0,
    )
    roles = RoleModelManifest((RoleModelAssignment("planner", deployment.deployment_id),))
    now = time.time()
    heartbeat = ServiceHeartbeat(
        deployment.deployment_id, stack.digest(), 123, "start-123", _digest("7"),
        True, certificate.digest(), now - 0.1,
    )
    heartbeat_ref = (
        f"heartbeat:{heartbeat.deployment_id}:{heartbeat.pid}:"
        f"{heartbeat.process_start_marker}:{heartbeat.timestamp}"
    )
    receipt = build_runtime_qualification_receipt(
        deployment, heartbeat, required_roles=("planner",),
        evidence_refs=(heartbeat_ref,), max_heartbeat_age_seconds=60.0, now=now,
    )
    canary = RuntimeCanaryEvidence(
        deployment_id=deployment.deployment_id,
        deployment_generation=deployment.digest(),
        route_digest=canonical_digest(route),
        role="planner",
        canary_id="planner-json",
        suite_digest=_digest("8"),
        process_pid=receipt.process_pid,
        process_start_marker=receipt.process_start_marker,
        argv_digest=receipt.argv_digest,
        request_digest=_digest("9"),
        probe_digest=_digest("0"),
        response_digest=_digest("a"),
        contract_digest=_digest("b"),
        passed=True,
        observed_at=now,
    )
    receipt = replace(
        receipt,
        evidence_refs=(*receipt.evidence_refs, f"canary:sha256:{canary.evidence_digest}"),
    )
    return QualifiedModelClosurePublication(
        role_manifest=roles,
        deployments=(deployment,),
        routes=(route,),
        runtime_manifest_digest=_digest("6"),
        runtime_qualification_receipts=(receipt,),
        runtime_canary_evidence=(canary,),
    )


def test_publisher_round_trip_produces_bindable_closure(tmp_path: Path) -> None:
    publication = _publication()
    path = tmp_path / "qualified.json"
    receipt = publish_qualified_model_deployment_closure(path, publication)

    closure = load_qualified_model_deployment_closure(
        path,
        runtime_qualification_store_factory=DirectoryRuntimeQualificationEvidenceStore,
        runtime_canary_store_factory=DirectoryRuntimeCanaryEvidenceStore,
    )
    binding = PersistedQualifiedModelEndpointBinding(closure).binding_for(
        role="planner", prompt_generation="prompt-v1"
    )

    assert receipt.closure_path == str(path.resolve())
    assert len(receipt.closure_digest) == 64
    assert len(receipt.runtime_evidence_paths) == 1
    assert len(receipt.runtime_canary_evidence_paths) == 1
    assert binding.deployment_id == "deployment-1"
    assert binding.max_admitted_concurrency == 2
    assert binding.runtime_qualification_digest == publication.runtime_qualification_receipts[0].digest()


def test_identical_replay_is_idempotent_and_conflict_is_rejected(tmp_path: Path) -> None:
    publication = _publication()
    path = tmp_path / "qualified.json"
    first = publish_qualified_model_deployment_closure(path, publication)
    before = path.read_bytes()
    second = publish_qualified_model_deployment_closure(path, publication)
    assert second.closure_digest == first.closure_digest
    assert path.read_bytes() == before

    changed_route = replace(publication.routes[0], base_url="http://127.0.0.1:30001")
    changed_canary = replace(
        publication.runtime_canary_evidence[0],
        route_digest=canonical_digest(changed_route),
        evidence_digest="",
    )
    old_canary_ref = f"canary:sha256:{publication.runtime_canary_evidence[0].evidence_digest}"
    new_canary_ref = f"canary:sha256:{changed_canary.evidence_digest}"
    changed_receipt = replace(
        publication.runtime_qualification_receipts[0],
        evidence_refs=tuple(
            new_canary_ref if ref == old_canary_ref else ref
            for ref in publication.runtime_qualification_receipts[0].evidence_refs
        ),
    )
    conflicting = replace(
        publication,
        routes=(changed_route,),
        runtime_qualification_receipts=(changed_receipt,),
        runtime_canary_evidence=(changed_canary,),
    )
    with pytest.raises(QualifiedModelClosurePublicationError, match="different content"):
        publish_qualified_model_deployment_closure(path, conflicting)
    assert path.read_bytes() == before


def test_valid_recomputed_digest_does_not_hide_type_corruption(tmp_path: Path) -> None:
    publication = _publication()
    path = tmp_path / "qualified.json"
    publish_qualified_model_deployment_closure(path, publication)
    document = json.loads(path.read_text(encoding="utf-8"))
    envelope = document["deployments"][0]["certificate"]["resource_envelope"]
    envelope["max_qualified_concurrency"] = "2"
    unsigned = {key: value for key, value in document.items() if key != "closure_digest"}
    document["closure_digest"] = canonical_digest(unsigned)
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(QualifiedModelClosureReadError):
        load_qualified_model_deployment_closure(
            path,
            runtime_qualification_store_factory=DirectoryRuntimeQualificationEvidenceStore,
            runtime_canary_store_factory=DirectoryRuntimeCanaryEvidenceStore,
        )


class _FailingReadbackStore:
    def publish(self, runtime_manifest_digest: str, receipt: RuntimeQualificationReceipt) -> str:
        del runtime_manifest_digest
        return f"memory:{receipt.deployment_id}"

    def load(self, runtime_manifest_digest: str, deployment_id: str) -> RuntimeQualificationReceipt:
        del runtime_manifest_digest, deployment_id
        raise OSError("injected readback failure")


def test_partial_runtime_publication_never_exposes_closure(tmp_path: Path) -> None:
    path = tmp_path / "qualified.json"
    with pytest.raises(QualifiedModelClosurePublicationError, match="runtime qualification publication"):
        _publish_with_store(
            path,
            _publication(),
            runtime_qualification_store_factory=lambda root: _FailingReadbackStore(),
            runtime_canary_store_factory=DirectoryRuntimeCanaryEvidenceStore,
        )
    assert not path.exists()


def test_runtime_receipt_must_cover_frozen_role_before_any_write(tmp_path: Path) -> None:
    publication = _publication()
    bad_receipt = replace(publication.runtime_qualification_receipts[0], qualified_roles=("critic",))
    invalid = replace(publication, runtime_qualification_receipts=(bad_receipt,))
    path = tmp_path / "qualified.json"
    with pytest.raises(QualifiedModelClosurePublicationError, match="frozen roles"):
        publish_qualified_model_deployment_closure(path, invalid)
    assert not path.exists()


def test_conflicting_closure_is_rejected_before_new_runtime_evidence(tmp_path: Path) -> None:
    publication = _publication()
    path = tmp_path / "qualified.json"
    publish_qualified_model_deployment_closure(path, publication)

    conflicting = replace(publication, runtime_manifest_digest=_digest("7"))
    with pytest.raises(QualifiedModelClosurePublicationError, match="different content"):
        publish_qualified_model_deployment_closure(path, conflicting)

    unexpected = tmp_path / publication.runtime_qualification_root / conflicting.runtime_manifest_digest
    assert not unexpected.exists()


def test_concurrent_identical_publishers_share_one_publication_domain(tmp_path: Path) -> None:
    publication = _publication()
    path = tmp_path / "qualified.json"
    barrier = threading.Barrier(6)
    receipts = []
    failures: list[BaseException] = []

    def publish() -> None:
        try:
            barrier.wait()
            receipts.append(publish_qualified_model_deployment_closure(path, publication))
        except BaseException as exc:
            failures.append(exc)

    threads = [threading.Thread(target=publish) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(3.0)

    assert all(not thread.is_alive() for thread in threads)
    assert failures == []
    assert len(receipts) == 6
    assert len({item.closure_digest for item in receipts}) == 1
    assert path.is_file()


def test_heartbeat_only_publication_is_rejected() -> None:
    publication = _publication()
    with pytest.raises(TypeError, match="runtime canary evidence"):
        replace(publication, runtime_canary_evidence=())


def test_failed_or_wrong_process_canary_cannot_publish(tmp_path: Path) -> None:
    publication = _publication()
    failed = replace(
        publication.runtime_canary_evidence[0],
        passed=False,
        evidence_digest="",
    )
    with pytest.raises(QualifiedModelClosurePublicationError, match="did not pass"):
        publish_qualified_model_deployment_closure(
            tmp_path / "failed.json",
            replace(publication, runtime_canary_evidence=(failed,)),
        )

    drifted = replace(
        publication.runtime_canary_evidence[0],
        process_start_marker="other-generation",
        evidence_digest="",
    )
    with pytest.raises(QualifiedModelClosurePublicationError, match="process generation drift"):
        publish_qualified_model_deployment_closure(
            tmp_path / "drifted.json",
            replace(publication, runtime_canary_evidence=(drifted,)),
        )


def test_loader_rejects_missing_runtime_canary_evidence(tmp_path: Path) -> None:
    publication = _publication()
    path = tmp_path / "qualified.json"
    receipt = publish_qualified_model_deployment_closure(path, publication)
    assert len(receipt.runtime_canary_evidence_paths) == 1
    Path(receipt.runtime_canary_evidence_paths[0]).unlink()

    with pytest.raises(QualifiedModelClosureReadError, match="runtime canary evidence"):
        load_qualified_model_deployment_closure(
            path,
            runtime_qualification_store_factory=DirectoryRuntimeQualificationEvidenceStore,
            runtime_canary_store_factory=DirectoryRuntimeCanaryEvidenceStore,
        )


def test_runtime_receipt_must_bind_exact_canary_evidence(tmp_path: Path) -> None:
    publication = _publication()
    receipt = publication.runtime_qualification_receipts[0]
    heartbeat_only = replace(
        receipt,
        evidence_refs=tuple(
            ref for ref in receipt.evidence_refs if not ref.startswith("canary:sha256:")
        ),
    )
    invalid = replace(publication, runtime_qualification_receipts=(heartbeat_only,))
    path = tmp_path / "qualified.json"
    with pytest.raises(
        QualifiedModelClosurePublicationError,
        match="does not bind runtime canary evidence",
    ):
        publish_qualified_model_deployment_closure(path, invalid)
    assert not path.exists()

def test_loader_rejects_validly_rechecksummed_runtime_receipt_drift(tmp_path: Path) -> None:
    publication = _publication()
    path = tmp_path / "qualified.json"
    published = publish_qualified_model_deployment_closure(path, publication)
    receipt_path = Path(published.runtime_evidence_paths[0])
    decoded = decode_checksummed_document(
        receipt_path.read_bytes(),
        expected_schema="runtime-qualification-receipt.v4",
    )
    payload = dict(decoded.payload)
    receipt_payload = dict(payload["receipt"])
    receipt_payload["evidence_refs"] = [
        *receipt_payload["evidence_refs"],
        "performance:sha256:" + _digest("d"),
    ]
    drifted = RuntimeQualificationReceipt(
        **{**receipt_payload, "qualified_roles": tuple(receipt_payload["qualified_roles"]),
           "evidence_refs": tuple(receipt_payload["evidence_refs"])}
    )
    payload["receipt"] = receipt_payload
    payload["receipt_digest"] = drifted.digest()
    receipt_path.write_bytes(
        encode_checksummed_document("runtime-qualification-receipt.v4", payload)
    )

    with pytest.raises(QualifiedModelClosureReadError, match="receipt digest drift"):
        load_qualified_model_deployment_closure(
            path,
            runtime_qualification_store_factory=DirectoryRuntimeQualificationEvidenceStore,
            runtime_canary_store_factory=DirectoryRuntimeCanaryEvidenceStore,
        )
