from __future__ import annotations

import json
from pathlib import Path

import pytest

from noetrium_platform.capabilities.model.asset.api import ManagedModelAsset, ModelAssetMode, ModelAssetOrigin
from noetrium_platform.capabilities.model.asset.runtime.codec import decode_model_asset, encode_model_asset
from noetrium_platform.capabilities.model.deployment.api import (
    ModelControllerPhase,
    ModelControllerState,
    ModelDeploymentSpec,
    ModelDeploymentStatus,
    ModelDesiredState,
    ModelReconcileCycle,
    ModelRuntimeState,
)
from noetrium_platform.capabilities.model.deployment.runtime.applied import AppliedModelDeployment
from noetrium_platform.capabilities.model.deployment.runtime.codec import (
    decode_applied,
    decode_deployment,
    deployment_to_data,
    encode_applied,
)
from noetrium_platform.capabilities.model.deployment.runtime.controller_state import FileModelControllerStateStore
from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE


_DIGEST = "a" * 64


def _deployment() -> ModelDeploymentSpec:
    return ModelDeploymentSpec(
        deployment_id="deployment:test",
        scope=PLATFORM_SCOPE,
        service_id="model:deployment:test",
        model_id="model:test",
        engine="test-engine",
        executable="C:/runtime/python.exe",
        argv=("C:/runtime/python.exe", "-m", "server"),
        cwd=Path("C:/runtime"),
        python_environment_id="env:test",
        gpu_devices=("GPU-0",),
        environment=(("TOKENIZERS_PARALLELISM", "false"),),
        readiness_url="http://127.0.0.1:18000/health",
        readiness_timeout_s=12.5,
        stop_timeout_s=7.0,
        heartbeat_interval_s=2.0,
        desired_state=ModelDesiredState.RUNNING,
        tags=("qualified",),
    )


def _contract() -> ServiceLaunchContract:
    return ServiceLaunchContract(
        service_id="model:deployment:test",
        generation="generation:test",
        executable="C:/runtime/python.exe",
        argv=("C:/runtime/python.exe", "-m", "server"),
        cwd="C:/runtime",
        environment_digest=_DIGEST,
        artifact_digest=_DIGEST,
        runtime_identity_digest=_DIGEST,
        readiness_timeout_s=12.5,
        stop_timeout_s=7.0,
        heartbeat_interval_s=2.0,
    )


def test_deployment_and_applied_snapshot_round_trip_exactly() -> None:
    deployment = _deployment()
    assert decode_deployment(deployment_to_data(deployment)) == deployment

    applied = AppliedModelDeployment(
        deployment,
        _contract(),
        (("CUDA_VISIBLE_DEVICES", "0"),),
    )
    assert decode_applied(json.loads(encode_applied(applied))) == applied


def test_model_asset_round_trip_exactly() -> None:
    asset = ManagedModelAsset(
        model_id="model:test",
        scope=PLATFORM_SCOPE,
        path=Path("C:/models/test"),
        mode=ModelAssetMode.REFERENCE,
        family="test-family",
        notes="verified source",
        origin=ModelAssetOrigin("huggingface", "owner/model", "revision-1"),
        tags=("large", "planner"),
        storage_pool="models",
    )
    assert decode_model_asset(json.loads(encode_model_asset(asset))) == asset


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("deployment_id", 123),
        ("argv", [1, "server"]),
        ("gpu_devices", [0]),
        ("readiness_timeout_s", "12.5"),
        ("heartbeat_interval_s", float("inf")),
        ("tags", [True]),
    ),
)
def test_deployment_decoder_rejects_type_coercion(field: str, value: object) -> None:
    document = deployment_to_data(_deployment())
    document[field] = value
    with pytest.raises(ValueError):
        decode_deployment(document)


def test_deployment_decoder_rejects_missing_extra_and_malformed_environment() -> None:
    missing = deployment_to_data(_deployment())
    missing.pop("engine")
    with pytest.raises(ValueError):
        decode_deployment(missing)

    extra = deployment_to_data(_deployment())
    extra["legacy_fallback"] = True
    with pytest.raises(ValueError):
        decode_deployment(extra)

    malformed_environment = deployment_to_data(_deployment())
    malformed_environment["environment"] = [["ONLY_ONE"]]
    with pytest.raises(ValueError):
        decode_deployment(malformed_environment)


def test_asset_decoder_rejects_scalar_and_nested_origin_coercion() -> None:
    document = json.loads(encode_model_asset(ManagedModelAsset(
        "model:test", PLATFORM_SCOPE, Path("C:/models/test")
    )))
    document["model_id"] = 456
    with pytest.raises(ValueError):
        decode_model_asset(document)

    document = json.loads(encode_model_asset(ManagedModelAsset(
        "model:test",
        PLATFORM_SCOPE,
        Path("C:/models/test"),
        origin=ModelAssetOrigin("source", "owner/model"),
    )))
    document["origin"]["backend"] = 1
    with pytest.raises(ValueError):
        decode_model_asset(document)


def test_applied_decoder_rejects_nested_contract_coercion() -> None:
    document = json.loads(encode_applied(AppliedModelDeployment(
        _deployment(), _contract(), (("CUDA_VISIBLE_DEVICES", "0"),)
    )))
    document["contract"]["heartbeat_interval_s"] = "2.0"
    with pytest.raises(ValueError):
        decode_applied(document)

    document = json.loads(encode_applied(AppliedModelDeployment(
        _deployment(), _contract(), (("CUDA_VISIBLE_DEVICES", "0"),)
    )))
    document["contract"]["unexpected"] = "legacy"
    with pytest.raises(ValueError):
        decode_applied(document)


def _controller_state() -> ModelControllerState:
    status = ModelDeploymentStatus(
        deployment_id="deployment:test",
        service_id="model:deployment:test",
        desired_state=ModelDesiredState.RUNNING,
        runtime_state=ModelRuntimeState.RUNNING,
        pid=4321,
        detail="ready",
    )
    return ModelControllerState(
        controller_id="controller:model",
        phase=ModelControllerPhase.RUNNING,
        pid=1234,
        started_at_utc="2026-08-29T00:00:00Z",
        heartbeat_at_utc="2026-08-29T00:00:01Z",
        interval_seconds=1.5,
        cycle_count=3,
        last_cycle=ModelReconcileCycle(2, "2026-08-29T00:00:01Z", (status,)),
        detail="healthy",
    )


def test_controller_state_round_trip_and_corruption_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "controller.json"
    store = FileModelControllerStateStore(path)
    expected = _controller_state()
    store.write(expected)
    assert store.read() == expected

    document = json.loads(path.read_text("utf-8"))
    document["cycle_count"] = "3"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError):
        store.read()


def test_controller_state_rejects_nested_status_shape_drift(tmp_path: Path) -> None:
    path = tmp_path / "controller.json"
    store = FileModelControllerStateStore(path)
    store.write(_controller_state())
    document = json.loads(path.read_text("utf-8"))
    document["last_cycle"]["statuses"][0]["legacy"] = True
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError):
        store.read()


def test_qualification_application_decoder_rejects_coercive_receipt_state() -> None:
    from noetrium_platform.capabilities.model.qualification.api import (
        DeploymentQualificationApplicationReceipt,
        InstallPackage,
        QualificationCommandReceipt,
        QualificationMaterializationStatus,
    )
    from noetrium_platform.capabilities.model.qualification.providers.qualification_application import (
        FileDeploymentQualificationApplicationStore,
    )

    receipt = DeploymentQualificationApplicationReceipt(
        plan_digest="1" * 64,
        environment_id="env:test",
        backend="vllm",
        packages=(InstallPackage("vllm", "1.0", "https://example.invalid/simple"),),
        install_commands=(QualificationCommandReceipt("install", "2" * 64, 0, "3" * 64, "4" * 64),),
        check_command=QualificationCommandReceipt("check", "5" * 64, 0, "6" * 64, "7" * 64),
        status=QualificationMaterializationStatus.SUCCEEDED,
    )
    payload = FileDeploymentQualificationApplicationStore._payload(receipt)
    payload["install_commands"][0]["return_code"] = "0"
    with pytest.raises(ValueError):
        FileDeploymentQualificationApplicationStore._receipt(payload)

    payload = FileDeploymentQualificationApplicationStore._payload(receipt)
    payload["legacy_field"] = True
    with pytest.raises(ValueError):
        FileDeploymentQualificationApplicationStore._receipt(payload)


def test_qualification_runtime_decoder_rejects_coercive_receipt_state() -> None:
    from noetrium_platform.capabilities.model.qualification.api import (
        DeploymentQualificationRuntimeReceipt,
        DeploymentRuntimeQualificationStatus,
        RuntimeCheckReceipt,
    )
    from noetrium_platform.capabilities.model.qualification.providers.qualification_runtime import (
        FileDeploymentQualificationRuntimeStore,
    )

    receipt = DeploymentQualificationRuntimeReceipt(
        application_digest="1" * 64,
        plan_digest="2" * 64,
        environment_id="env:test",
        backend="vllm",
        checks=(RuntimeCheckReceipt("backend-import", "3" * 64, 0, "4" * 64, "5" * 64),),
        status=DeploymentRuntimeQualificationStatus.PASSED,
    )
    payload = FileDeploymentQualificationRuntimeStore._payload(receipt)
    payload["checks"][0]["return_code"] = False
    with pytest.raises(ValueError):
        FileDeploymentQualificationRuntimeStore._receipt(payload)

    payload = FileDeploymentQualificationRuntimeStore._payload(receipt)
    payload["checks"][0]["legacy_field"] = "ignored-before"
    with pytest.raises(ValueError):
        FileDeploymentQualificationRuntimeStore._receipt(payload)
