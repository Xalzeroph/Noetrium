from __future__ import annotations

import json
from pathlib import Path

import pytest

from noetrium_platform.capabilities.model.qualification.api import (
    DeploymentQualificationApplicationReceipt,
    DeploymentQualificationRuntimeReceipt,
    DeploymentRuntimeQualificationStatus,
    InstallPackage,
    QualificationCommandReceipt,
    QualificationMaterializationStatus,
    RuntimeCheckReceipt,
)
from noetrium_platform.capabilities.model.qualification.providers.qualification_application import (
    FileDeploymentQualificationApplicationStore,
    QualificationApplicationIntegrityError,
)
from noetrium_platform.capabilities.model.qualification.providers.qualification_runtime import (
    FileDeploymentQualificationRuntimeStore,
    QualificationRuntimeIntegrityError,
)
from noetrium_platform.capabilities.model.request.api import ModelRequestEnvelope
from noetrium_platform.evidence.artifact.content.api import ArtifactBlobRef
from noetrium_platform.capabilities.model.request.runtime.ledger import DirectoryModelRequestLedger
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, ImmutableModelIdentity
from noetrium_platform.foundation.kernel.kernel.durability import (
    decode_checksummed_document,
    encode_checksummed_document,
)

_PLAN_DIGEST = "a" * 64
_APPLICATION_SCHEMA = "model-deployment-qualification-application.v1"
_RUNTIME_SCHEMA = "model-deployment-qualification-runtime.v2"


def _application() -> DeploymentQualificationApplicationReceipt:
    return DeploymentQualificationApplicationReceipt(
        plan_digest=_PLAN_DIGEST,
        environment_id="serving-env",
        backend="vllm",
        packages=(InstallPackage("vllm", "1.0", "https://index.example/simple"),),
        install_commands=(
            QualificationCommandReceipt("pip-install", "b" * 64, 0, "c" * 64, "d" * 64),
        ),
        check_command=QualificationCommandReceipt(
            "pip-check", "e" * 64, 0, "f" * 64, "1" * 64
        ),
        status=QualificationMaterializationStatus.SUCCEEDED,
        reasons=(),
    )


def _runtime(application_digest: str) -> DeploymentQualificationRuntimeReceipt:
    return DeploymentQualificationRuntimeReceipt(
        application_digest=application_digest,
        plan_digest=_PLAN_DIGEST,
        environment_id="serving-env",
        backend="vllm",
        checks=(RuntimeCheckReceipt("backend-import", "2" * 64, 0, "3" * 64, "4" * 64),),
        status=DeploymentRuntimeQualificationStatus.PASSED,
        reasons=(),
    )

def test_application_store_rejects_rechecksummed_type_drift(tmp_path: Path) -> None:
    store = FileDeploymentQualificationApplicationStore(tmp_path / "applications")
    receipt = _application()
    store.publish(receipt)
    path = tmp_path / "applications" / f"{receipt.application_digest}.json"
    document = decode_checksummed_document(path.read_bytes(), expected_schema=_APPLICATION_SCHEMA)
    payload = dict(document.payload)
    payload["environment_id"] = 123
    path.write_bytes(encode_checksummed_document(_APPLICATION_SCHEMA, payload))

    with pytest.raises(QualificationApplicationIntegrityError):
        store.get(receipt.application_digest)


def test_application_store_rejects_null_command_in_rechecksummed_list(tmp_path: Path) -> None:
    store = FileDeploymentQualificationApplicationStore(tmp_path / "applications")
    receipt = _application()
    store.publish(receipt)
    path = tmp_path / "applications" / f"{receipt.application_digest}.json"
    document = decode_checksummed_document(path.read_bytes(), expected_schema=_APPLICATION_SCHEMA)
    payload = dict(document.payload)
    payload["install_commands"] = [None]
    path.write_bytes(encode_checksummed_document(_APPLICATION_SCHEMA, payload))

    with pytest.raises(QualificationApplicationIntegrityError):
        store.get(receipt.application_digest)

def test_runtime_store_rejects_rechecksummed_nested_type_drift(tmp_path: Path) -> None:
    application = _application()
    receipt = _runtime(application.application_digest)
    store = FileDeploymentQualificationRuntimeStore(tmp_path / "runtime")
    store.publish(receipt)
    path = tmp_path / "runtime" / f"{receipt.runtime_digest}.json"
    document = decode_checksummed_document(path.read_bytes(), expected_schema=_RUNTIME_SCHEMA)
    payload = dict(document.payload)
    checks = [dict(item) for item in payload["checks"]]
    checks[0]["return_code"] = "0"
    payload["checks"] = checks
    path.write_bytes(encode_checksummed_document(_RUNTIME_SCHEMA, payload))

    with pytest.raises(QualificationRuntimeIntegrityError):
        store.get(receipt.runtime_digest)


def _envelope() -> ModelRequestEnvelope:
    return ModelRequestEnvelope(
        schema_version="model-request.v1",
        request_id="request:1",
        context=ExecutionContext(
            "run:1", "trace:1", "span:1", participant_generations=(("planner", "gen:1"),)
        ),
        role="planner",
        model=ImmutableModelIdentity(
            "planner", "model:1", "rev:1", "vllm", "1.0", "bfloat16", None, 8192
        ),
        prompt_generation_id="prompt-gen:1",
        prompt_id="planner.prompt",
        prompt_digest="5" * 64,
        request_body=ArtifactBlobRef("6" * 64, 10, "application/json"),
        source_artifact_refs=("artifact:1",),
        source_state_refs=("state:1",),
    )

def test_request_ledger_rejects_source_ref_type_coercion(tmp_path: Path) -> None:
    ledger = DirectoryModelRequestLedger(tmp_path / "requests")
    envelope = _envelope()
    ledger.append(envelope)
    path = ledger._path(envelope.request_id)
    payload = json.loads(path.read_text("utf-8"))
    payload["source_artifact_refs"] = [123]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        ledger.get(envelope.request_id)


def test_request_ledger_rejects_nested_context_type_coercion(tmp_path: Path) -> None:
    ledger = DirectoryModelRequestLedger(tmp_path / "requests")
    envelope = _envelope()
    ledger.append(envelope)
    path = ledger._path(envelope.request_id)
    payload = json.loads(path.read_text("utf-8"))
    payload["context"]["participant_generations"] = [["planner", 7]]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        ledger.get(envelope.request_id)


def test_request_ledger_rejects_unknown_persisted_fields(tmp_path: Path) -> None:
    ledger = DirectoryModelRequestLedger(tmp_path / "requests")
    envelope = _envelope()
    ledger.append(envelope)
    path = ledger._path(envelope.request_id)
    payload = json.loads(path.read_text("utf-8"))
    payload["legacy_fallback"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        ledger.get(envelope.request_id)

def test_request_ledger_round_trips_exact_envelope(tmp_path: Path) -> None:
    ledger = DirectoryModelRequestLedger(tmp_path / "requests")
    envelope = _envelope()
    ledger.append(envelope)
    assert ledger.get(envelope.request_id) == envelope