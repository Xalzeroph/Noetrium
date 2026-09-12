from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from noetrium_platform.capabilities.model.request.prompt.runtime.budget import (
    ModelRequestBudgetExceeded,
    check_model_request_budget,
)
from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract
from noetrium_platform.infrastructure.lifecycle.service.runtime.environment import (
    MaterializedServiceEnvironment,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime.preflight import (
    LocalServiceLaunchPreflight,
    ServiceLaunchPreflightError,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def service_contract(tmp_path: Path, *, required_paths: tuple[str, ...] = ()) -> ServiceLaunchContract:
    environment = MaterializedServiceEnvironment.from_mapping({"PATH": "/usr/bin"}, "env:test")
    return ServiceLaunchContract(
        service_id="test.service",
        generation="test-v1",
        executable="/bin/sh",
        argv=("/bin/sh", "-c", "true"),
        cwd=str(tmp_path),
        environment_digest=environment.digest,
        artifact_digest=digest("artifact"),
        runtime_identity_digest=digest("runtime"),
        readiness_timeout_s=1.0,
        stop_timeout_s=1.0,
        heartbeat_interval_s=1.0,
    )


def test_model_request_budget_blocks_before_provider_use() -> None:
    class ExactCounter:
        def count(self, text: str) -> int:
            return 90

    with pytest.raises(ModelRequestBudgetExceeded) as raised:
        check_model_request_budget(
            {"messages": [{"role": "user", "content": "hello"}], "max_tokens": 20},
            context_length=100,
            token_counter=ExactCounter(),
        )
    assert raised.value.report.input_tokens == 90
    assert raised.value.report.available_input_tokens == 80
    assert raised.value.report.counter_kind == "exact"


def test_model_request_budget_accepts_explicitly_fitting_request() -> None:
    report = check_model_request_budget(
        {"messages": [{"role": "user", "content": "hello"}], "max_tokens": 20},
        context_length=100,
        token_counter=type("Counter", (), {"count": lambda self, text: 70})(),
        safety_tokens=5,
    )
    assert report is not None
    assert report.fits
    assert report.total_tokens == 95


def test_model_request_budget_rejects_invalid_output_reservation() -> None:
    with pytest.raises(ValueError, match="max_tokens"):
        check_model_request_budget({"max_tokens": True}, context_length=100)


def test_service_preflight_reports_missing_runtime_inputs(tmp_path: Path) -> None:
    contract = service_contract(tmp_path)
    environment = MaterializedServiceEnvironment.from_mapping({"PATH": "/usr/bin"}, "env:test")
    required = tmp_path / "server.properties"
    report = LocalServiceLaunchPreflight(required_paths=(str(required),)).inspect(contract, environment)
    assert not report.ready
    assert "required service resource is missing" in report.errors[0]
    with pytest.raises(ServiceLaunchPreflightError):
        LocalServiceLaunchPreflight(required_paths=(str(required),)).validate(contract, environment)


def test_service_preflight_accepts_complete_runtime_inputs(tmp_path: Path) -> None:
    required = tmp_path / "server.properties"
    required.write_text("motd=test", encoding="utf-8")
    contract = service_contract(tmp_path)
    environment = MaterializedServiceEnvironment.from_mapping({"PATH": "/usr/bin"}, "env:test")
    report = LocalServiceLaunchPreflight(required_paths=(str(required),)).validate(contract, environment)
    assert report.ready
    assert all(passed for _, passed in report.checks)
