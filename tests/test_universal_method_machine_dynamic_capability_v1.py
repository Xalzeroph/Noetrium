from __future__ import annotations

import pytest

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
)
from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import EffectClass, ExecutionContext
from noetrium_platform.research.execution.workflow.api import (
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
    MethodRuntimeContext,
    MethodRunStatus,
)
from noetrium_platform.research.execution.workflow.runtime import UniversalMethodMachine


def _identity(name: str) -> MethodProgramIdentity:
    return MethodProgramIdentity(
        MethodIdentity(
            name,
            "1",
            "noetrium.method-machine.v1",
            "dynamic-capability.v1",
        )
    )


def _target(request: MethodNodeRequest) -> str:
    value = request.state.get("capability")
    if not isinstance(value, str):
        raise TypeError("capability must be text")
    return value


def _prepare(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(value={"value": request.state["value"]})


def _finish(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(value=request.previous_value)


def _program(capability_ids: tuple[str, ...]) -> MethodProgram:
    builder = MethodProgramBuilder(_identity("dynamic-tool"), entrypoint="prepare")
    builder.compute("prepare", "dynamic-tool.prepare", _prepare, ("invoke",))
    builder.dynamic_capability(
        "invoke",
        "dynamic-tool.invoke",
        capability_ids,
        _target,
        ("return",),
        effect_class=EffectClass.NON_IDEMPOTENT,
    )
    builder.return_node("return", "dynamic-tool.return", _finish)
    return builder.build()


class _Capabilities:
    def __init__(self) -> None:
        self.requests: list[CapabilityRequest] = []

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        effect = (
            EffectClass.PURE
            if capability_id == "tool.read"
            else EffectClass.IDEMPOTENT
        )
        return CapabilityDescriptor(
            capability_id,
            "1",
            "json",
            "json",
            effect,
        )

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        self.requests.append(request)
        return CapabilityResult(
            request.capability_id,
            {
                "selected": request.capability_id,
                "payload": request.payload,
            },
        )


def _run(capability: str):
    port = _Capabilities()
    result = UniversalMethodMachine().run(
        _program(("tool.read", "tool.write")),
        runtime=MethodRuntimeContext(
            ExecutionContext("run", "trace", "span"),
            capabilities=port,
        ),
        initial_state={"capability": capability, "value": 7},
    )
    return result, port


def test_dynamic_capability_selects_from_frozen_closure_and_uses_runtime_descriptor() -> None:
    pure_result, pure = _run("tool.read")
    assert pure_result.status is MethodRunStatus.SUCCEEDED
    assert pure_result.value["selected"] == "tool.read"
    assert pure.requests[0].idempotency_key is None

    effect_result, effect = _run("tool.write")
    assert effect_result.status is MethodRunStatus.SUCCEEDED
    assert effect_result.value["selected"] == "tool.write"
    assert effect.requests[0].idempotency_key is not None


def test_dynamic_capability_rejects_target_outside_frozen_closure() -> None:
    result, port = _run("tool.delete")
    assert result.status is MethodRunStatus.FAILED
    assert "undeclared capability" in (result.failure or "")
    assert port.requests == []


def test_dynamic_capability_target_closure_changes_graph_identity() -> None:
    left = _program(("tool.read", "tool.write"))
    right = _program(("tool.read", "tool.delete"))
    assert left.graph.graph_digest != right.graph.graph_digest
    assert left.program_digest != right.program_digest
