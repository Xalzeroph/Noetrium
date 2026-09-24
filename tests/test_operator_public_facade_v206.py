from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from noetrium import api
from noetrium_platform.product.operator.api import (
    ResearchAction,
    ResearchFacade,
    ResearchRequest,
    ResearchResult,
)
from noetrium_platform.product.operator.api.json_rendering import plain_json
from noetrium_platform.product.operator.runtime.research_cli import build_research_parser
from noetrium_platform.composition.operator.wiring.research import main


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


def test_research_parser_exposes_canonical_research_os_control_surface():
    parser = build_research_parser()
    commands = tuple(action.value for action in api.ResearchControlAction)
    assert commands == (
        "run",
        "inspect",
        "pause",
        "drain",
        "interrupt",
        "resume",
        "retry",
        "cancel",
        "checkpoint",
        "reconcile",
        "migrate",
    )
    for command in commands:
        args = parser.parse_args([command, "run-1", "--project", "."])
        assert args.action.value == command
        assert args.route == "project"
        assert args.project_root == Path(".")


class _ProjectResearchOS:
    def __init__(self) -> None:
        self.calls = []

    def run(self, target, payload=None):
        self.calls.append(("run", target, payload))
        return {
            "action": "run",
            "execution_id": target.execution_id,
            "revision_digest": target.revision.revision_digest,
            "node": (
                None
                if target.node is None
                else {
                    "program_id": target.node.program_id,
                    "node_id": target.node.node_id,
                }
            ),
            "payload": payload,
        }

    def reconcile(self, target, payload=None):
        del target, payload
        raise ValueError("lower-authority reconciliation proof is unavailable")


class _LoadedResearchOS:
    def __init__(self, research_os) -> None:
        self.research_os = research_os
        self.default_execution_id = "project-default"
        self.revision = api.ResearchGraphRevision(
            "paper",
            "a" * 64,
            (),
            "working",
        )
        self.active_revision = self.revision
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_lifecycle_cli_routes_directly_through_project_research_os(capsys):
    research_os = _ProjectResearchOS()
    loaded = _LoadedResearchOS(research_os)
    with patch(
        "noetrium_platform.composition.operator.wiring.research.load_project_research_os",
        return_value=loaded,
    ):
        rc = main([
            "run",
            "run-7",
            "--project",
            ".",
            "--program",
            "paper",
            "--node",
            "source",
            "--payload",
            '{"seed": 7}',
        ])
    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["result"]["action"] == "run"
    assert output["result"]["execution_id"] == "run-7"
    assert output["result"]["node"] == {
        "program_id": "paper",
        "node_id": "source",
    }
    action, target, payload = research_os.calls[0]
    assert action == "run"
    assert target.node == api.ResearchNodeRef("paper", "source")
    assert payload["seed"] == 7
    assert loaded.closed is True


def test_lifecycle_cli_fails_closed_on_research_os_control_error(capsys):
    loaded = _LoadedResearchOS(_ProjectResearchOS())
    with patch(
        "noetrium_platform.composition.operator.wiring.research.load_project_research_os",
        return_value=loaded,
    ):
        rc = main([
            "reconcile",
            "run-7",
            "--project",
            ".",
            "--program",
            "paper",
            "--node",
            "source",
        ])
    assert rc == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["ok"] is False
    assert error["command"] == "reconcile"
    assert error["error_type"] == "ValueError"
    assert loaded.closed is True


def test_manage_route_preserves_foreign_cli_arguments_verbatim():
    with patch(
        "noetrium_platform.composition.operator.maintenance_wiring.cli._management_main",
        return_value=0,
    ) as downstream:
        assert main(["manage", "--config", "management.json", "summary"]) == 0
    downstream.assert_called_once_with(["--config", "management.json", "summary"])


def test_diagnose_route_preserves_foreign_cli_arguments_verbatim():
    with patch(
        "noetrium_platform.composition.operator.wiring.research.diagnose_main",
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
