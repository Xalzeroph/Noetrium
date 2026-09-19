from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from noetrium_platform.api import (
    ResearchAction,
    ResearchFacade,
    ResearchOperationFailure,
    ResearchRequest,
    ResearchResult,
)
from noetrium_platform.product.operator.api.json_rendering import plain_json
from noetrium_platform.product.operator.runtime.research_cli import build_research_parser
from noetrium_platform.product.operator.composition.research import main


class _Application:
    def __init__(self) -> None:
        self.requests: list[ResearchRequest] = []

    def execute(self, request: ResearchRequest) -> ResearchResult:
        self.requests.append(request)
        return ResearchResult(
            request.action,
            request.target,
            "accepted",
            {"request_action": request.action.value, "input": request.payload},
        )


def test_canonical_facade_exposes_six_lifecycle_surfaces():
    app = _Application()
    facade = ResearchFacade(app)
    operations = ("run", "inspect", "stop", "resume", "reconcile", "evidence")
    for operation in operations:
        result = getattr(facade, operation)("run-1", {"operation": operation})
        assert result.action.value == operation
        assert result.target == "run-1"
    assert [request.action.value for request in app.requests] == list(operations)


def test_request_payload_is_deeply_frozen_at_facade_boundary():
    payload = {"items": [{"value": 1}]}
    request = ResearchRequest(ResearchAction.RUN, "run-1", payload)
    payload["items"][0]["value"] = 99
    assert request.payload["items"][0]["value"] == 1
    with pytest.raises(TypeError):
        request.payload["new"] = "forbidden"


def test_facade_rejects_application_result_identity_drift():
    class _BadApplication:
        def execute(self, request: ResearchRequest) -> ResearchResult:
            return ResearchResult(ResearchAction.STOP, request.target, "wrong-action")

    with pytest.raises(ValueError, match="identity"):
        ResearchFacade(_BadApplication()).run("run-1")


def test_research_parser_has_one_common_lifecycle_surface():
    parser = build_research_parser()
    for command in ("run", "inspect", "stop", "resume", "reconcile", "evidence"):
        args = parser.parse_args(["--application", "sample:factory", command, "run-1"])
        assert args.action.value == command
        assert args.route == "application"


def test_lifecycle_cli_requires_explicit_project_or_application_binding(capsys):
    assert main(["run", "run-1"]) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["ok"] is False
    assert error["error"] == "noetrium run requires --project PATH or --application MODULE:FACTORY"


def test_lifecycle_cli_delegates_to_explicit_application(capsys):
    app = _Application()
    with patch(
        "noetrium_platform.product.operator.runtime.research_cli.load_research_application",
        return_value=app,
    ):
        rc = main(
            [
                "--application",
                "sample:factory",
                "run",
                "run-7",
                "--payload",
                '{"seed": 7}',
            ]
        )
    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["result"]["action"] == "run"
    assert output["result"]["target"] == "run-7"
    assert app.requests[0].payload["seed"] == 7


def test_lifecycle_cli_preserves_authoritative_operation_failure(capsys):
    class _FailingApplication:
        def execute(self, request: ResearchRequest) -> ResearchResult:
            raise ResearchOperationFailure(
                ResearchResult(
                    request.action,
                    request.target,
                    "recovery_required",
                    {"control_revision": 3, "operation_id": "a" * 64},
                )
            )

    with patch(
        "noetrium_platform.product.operator.runtime.research_cli.load_research_application",
        return_value=_FailingApplication(),
    ):
        rc = main([
            "--application", "sample:factory", "reconcile", "run-7",
            "--payload", '{"expected_revision": 3}',
        ])
    assert rc == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["ok"] is False
    assert error["command"] == "reconcile"
    assert error["result"]["state"] == "recovery_required"
    assert error["result"]["payload"]["control_revision"] == 3


def test_manage_route_preserves_foreign_cli_arguments_verbatim():
    with patch(
        "noetrium_platform.product.operator.maintenance.composition.cli._management_main",
        return_value=0,
    ) as downstream:
        assert main(["manage", "--config", "management.json", "summary"]) == 0
    downstream.assert_called_once_with(["--config", "management.json", "summary"])


def test_diagnose_route_preserves_foreign_cli_arguments_verbatim():
    with patch(
        "noetrium_platform.product.operator.composition.research.diagnose_main",
        return_value=0,
    ) as downstream:
        assert main(["diagnose", "status", "run-root"]) == 0
    downstream.assert_called_once_with(["status", "run-root"])


class _IntCode(IntEnum):
    VALUE = 1


class _TextCode(StrEnum):
    VALUE = "value"


@dataclass(frozen=True)
class _StructuredValue:
    value: int


@pytest.mark.parametrize(
    "value",
    [
        _IntCode.VALUE,
        _TextCode.VALUE,
        b"bytes",
        Path("path"),
        {"set-member"},
        _StructuredValue(1),
        {1: "non-string-key"},
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_facade_consumes_role01_strict_finite_json_contract(value):
    with pytest.raises(TypeError):
        ResearchRequest(ResearchAction.RUN, "run-1", {"value": value})
    with pytest.raises(TypeError):
        ResearchResult(ResearchAction.RUN, "run-1", "accepted", {"value": value})


def test_product_json_renderer_rejects_mapping_key_coercion():
    with pytest.raises(TypeError, match="native string keys"):
        plain_json({1: "must-not-be-stringified"})
