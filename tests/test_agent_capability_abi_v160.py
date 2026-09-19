from __future__ import annotations

from tests_support import FakeParticipantResolver, frozen_binding

from collections.abc import Mapping
from dataclasses import dataclass
from types import NoneType
from typing import get_args, get_origin, get_type_hints

from noetrium_platform.capabilities.participant.agent.api import AgentIdentity, AgentTurnRequest, AgentTurnResult
from noetrium_platform.capabilities.participant.agent.api.cognition_ports import AgentDiagnosticsPort
from noetrium_platform.capabilities.participant.method.api import MethodSession
from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityProviderIdentity,
    CapabilityRequest,
    CapabilityResult,
)
from noetrium_platform.foundation.kernel.kernel import EffectClass, ExecutionContext


class EchoCapabilitySession:
    @property
    def capabilities(self):
        return (CapabilityDescriptor("echo", "1", "echo.req.v1", "echo.res.v1", EffectClass.PURE, True),)

    def invoke(self, request: CapabilityRequest):
        return CapabilityResult(request.capability_id, request.payload)

    def checkpoint(self): return b"{}"
    def restore(self, payload): return None
    def close(self): return None


class EchoProvider:
    identity = CapabilityProviderIdentity("echo-provider", "1", "1", "1", "cfg")
    def open_session(self, *, session_id: str, services: object): return EchoCapabilitySession()


class GenericAgent:
    identity = AgentIdentity("generic", "1", "1", "1", "a" * 64)
    def open_session(self, *, session_id: str, services: object): return object()


def test_participant_diagnostic_ports_expose_mapping_json_contracts():
    event_attributes = get_type_hints(AgentDiagnosticsPort.event)["attributes"]
    non_none = next(item for item in get_args(event_attributes) if item is not NoneType)
    method_diagnostics = get_type_hints(MethodSession.diagnostics)["return"]

    assert get_origin(non_none) is Mapping
    assert get_origin(method_diagnostics) is Mapping


def test_agent_and_capability_registries_are_independent():
    agents = FakeParticipantResolver()
    providers = FakeParticipantResolver()
    agents.register("agent", "generic", GenericAgent)
    providers.register("capability_provider", "echo-provider", EchoProvider)
    assert agents.resolve(frozen_binding("agent", "agent", "generic")).endpoint.identity.agent_id == "generic"
    assert providers.resolve(frozen_binding("capability_provider", "capability_provider", "echo-provider")).endpoint.identity.provider_id == "echo-provider"


def test_capability_contract_is_environment_agnostic():
    ctx = ExecutionContext("run", "trace", "span")
    request = CapabilityRequest("echo", {"x": 1}, ctx, "slot-1")
    result = EchoCapabilitySession().invoke(request)
    assert result.payload == {"x": 1}
    assert EchoCapabilitySession().capabilities[0].effect_class is EffectClass.PURE


def test_agent_turn_contract_carries_no_concrete_substrate_type():
    ctx = ExecutionContext("run", "trace", "span")
    request = AgentTurnRequest("do something", ctx, {"input": 1})
    result = AgentTurnResult({"done": True}, "agent-g1")
    assert request.task == "do something"
    assert result.agent_generation == "agent-g1"


def test_agent_turn_json_boundary_is_deeply_immutable():
    ctx = ExecutionContext("run", "trace", "span")
    task = {"steps": [{"name": "inspect"}]}
    payload = {"items": ["a"]}
    output = {"plan": [{"action": "move"}]}
    diagnostics = {"trace": {"verified": True}}
    request = AgentTurnRequest(task, ctx, payload)
    result = AgentTurnResult(output, "agent-g1", ("artifact:1",), diagnostics)

    task["steps"][0]["name"] = "caller-mutated"
    payload["items"].append("b")
    output["plan"][0]["action"] = "caller-mutated"
    diagnostics["trace"]["verified"] = False
    assert request.task["steps"][0]["name"] == "inspect"
    assert request.input_payload["items"] == ("a",)
    assert result.output["plan"][0]["action"] == "move"
    assert result.diagnostics["trace"]["verified"] is True

    import pytest
    with pytest.raises(TypeError): request.task["steps"][0]["name"] = "tampered"
    with pytest.raises((TypeError, AttributeError)): request.input_payload["items"].append("tampered")
    assert result.output["plan"] == ({"action": "move"},)
    assert isinstance(result.output["plan"], tuple)
    with pytest.raises(TypeError):
        result.output["plan"][0]["action"] = "tampered"
    with pytest.raises(TypeError): result.diagnostics["trace"]["verified"] = False
    with pytest.raises(TypeError): dict.__setitem__(result.output, "bypass", True)
    with pytest.raises(TypeError): dict.__setitem__(result.diagnostics, "bypass", True)
    with pytest.raises(TypeError): list.append(result.output["plan"], {"action": "bypass"})


def test_agent_turn_json_boundary_rejects_non_json_authority_values():
    import pytest
    from noetrium_platform.foundation.kernel.kernel import CanonicalEncodingError
    ctx = ExecutionContext("run", "trace", "span")
    with pytest.raises(CanonicalEncodingError, match="non-finite"):
        AgentTurnRequest({"score": float("nan")}, ctx)
    with pytest.raises(CanonicalEncodingError, match="non-finite"):
        AgentTurnResult({"score": float("inf")})
    recursive = {}
    recursive["self"] = recursive
    with pytest.raises(CanonicalEncodingError, match="cyclic"):
        AgentTurnRequest(recursive, ctx)
    with pytest.raises(TypeError, match="tuple of non-empty strings"):
        AgentTurnResult({"ok": True}, artifacts=["artifact:1"])


def test_capability_request_and_result_json_are_immutable_authority_values():
    import pytest
    ctx = ExecutionContext("run", "trace", "span")
    request_payload = {"steps": [{"name": "inspect"}]}
    result_payload = {"items": ["a"]}
    diagnostics = {"trace": {"ok": True}}
    request = CapabilityRequest("echo", request_payload, ctx, "slot-1")
    result = CapabilityResult("echo", result_payload, diagnostics=diagnostics)

    request_payload["steps"][0]["name"] = "caller-mutated"
    result_payload["items"].append("b")
    diagnostics["trace"]["ok"] = False
    assert request.payload["steps"] == ({"name": "inspect"},)
    assert result.payload["items"] == ("a",)
    assert result.diagnostics["trace"]["ok"] is True

    with pytest.raises(TypeError):
        request.payload["steps"][0]["name"] = "tampered"
    with pytest.raises(TypeError):
        result.diagnostics["trace"]["ok"] = False
