from __future__ import annotations

import pytest

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityResult,
)
from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import EffectClass, canonical_digest
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentResult,
    MethodNodeResult,
    MethodProgramBuilder,
    MethodRuntimePort,
)
from noetrium_platform.research.execution.workflow.composition import (
    MethodAgentLoopRouter,
    MethodRuntimePortInventory,
    plan_method_runtime_binding,
)


class _Loop:
    def __init__(self, name: str) -> None:
        self.identity_digest = canonical_digest({"loop": name})

    def run(self, request):
        return MethodAgentResult(value={"agent": request.agent_id})


class _Capabilities:
    def __init__(self, ids: tuple[str, ...]) -> None:
        self._ids = frozenset(ids)
        self.identity_digest = canonical_digest({"caps": tuple(sorted(ids))})

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        if capability_id not in self._ids:
            raise KeyError(capability_id)
        return CapabilityDescriptor(
            capability_id,
            "1",
            "json",
            "json",
            EffectClass.PURE,
            True,
        )

    def invoke(self, request):
        self.describe(request.capability_id)
        return CapabilityResult(request.capability_id, request.payload)


class _Children:
    identity_digest = canonical_digest({"children": "test"})

    def execute(self, request):
        return request

    def step_once(self, request):
        return request


def _program():
    identity = MethodProgramIdentity(MethodIdentity("auto.bind.test", "1", "1", "1"))

    def view(request):
        return {"instruction": "act", "state": request.state}

    def done(request):
        return MethodNodeResult(value=request.previous_value)

    return (
        MethodProgramBuilder(identity, entrypoint="reason")
        .agent("reason", "test.reason", "agent-a", ("tool",), view_handler=view)
        .capability("tool", "test.tool", "tool.echo", ("done",))
        .return_node("done", "test.done", done)
        .build(required_runtime_ports=(MethodRuntimePort.CHILD_MACHINES,))
    )


def test_runtime_binding_plan_resolves_declared_closure_from_explicit_inventory() -> None:
    router = MethodAgentLoopRouter({"agent-a": _Loop("a")})
    inventory = MethodRuntimePortInventory(
        agent_loop=router,
        capabilities=_Capabilities(("tool.echo",)),
        child_machines=_Children(),
    )
    plan = plan_method_runtime_binding(_program(), inventory)

    assert plan.complete is True
    assert plan.missing_ports == ()
    assert plan.missing_agent_ids == ()
    assert plan.missing_capability_ids == ()
    assert tuple(name for name, _ in plan.selected_port_digests) == (
        "agent_loop",
        "capabilities",
        "child_machines",
    )
    assert len(plan.digest) == 64


def test_runtime_binding_plan_fails_closed_on_missing_agent_identity() -> None:
    inventory = MethodRuntimePortInventory(
        agent_loop=MethodAgentLoopRouter({"agent-b": _Loop("b")}),
        capabilities=_Capabilities(("tool.echo",)),
        child_machines=_Children(),
    )
    plan = plan_method_runtime_binding(_program(), inventory)
    assert plan.complete is False
    assert plan.missing_agent_ids == ("agent-a",)
    with pytest.raises(RuntimeError, match="agent:agent-a"):
        plan.require_complete()


def test_runtime_binding_plan_fails_closed_on_missing_capability() -> None:
    inventory = MethodRuntimePortInventory(
        agent_loop=MethodAgentLoopRouter({"agent-a": _Loop("a")}),
        capabilities=_Capabilities(("tool.other",)),
        child_machines=_Children(),
    )
    plan = plan_method_runtime_binding(_program(), inventory)
    assert plan.complete is False
    assert plan.missing_capability_ids == ("tool.echo",)
    with pytest.raises(RuntimeError, match="capability:tool.echo"):
        plan.require_complete()


def test_runtime_binding_plan_reports_missing_port_without_fallback() -> None:
    inventory = MethodRuntimePortInventory(
        agent_loop=MethodAgentLoopRouter({"agent-a": _Loop("a")}),
        capabilities=_Capabilities(("tool.echo",)),
    )
    plan = plan_method_runtime_binding(_program(), inventory)
    assert plan.complete is False
    assert plan.missing_ports == (MethodRuntimePort.CHILD_MACHINES,)
