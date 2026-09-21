from __future__ import annotations

import pytest

from noetrium_platform.capabilities.participant.method.api import MethodIdentity, MethodProgramIdentity
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.research.execution.workflow.api import (
    MethodNodeResult,
    MethodProgramBuilder,
    MethodRuntimeContext,
    MethodRuntimePort,
    analyze_method_runtime_requirements,
)


def _identity(name: str) -> MethodProgramIdentity:
    return MethodProgramIdentity(MethodIdentity(name, "1", "1", "1"))


def _view(request):
    return {"input": request.input_value}


def _finish(request):
    return MethodNodeResult(value=request.previous_value)


def test_runtime_requirements_are_inferred_from_agent_and_capability_graph() -> None:
    program = (
        MethodProgramBuilder(_identity("requirements.graph"), entrypoint="agent")
        .agent("agent", "model.invoke", "planner", ("tool",), view_handler=_view)
        .capability("tool", "tool.invoke", "env.step", ("return",))
        .return_node("return", "return", _finish)
        .build(required_capabilities=("env.reset",))
    )
    requirements = analyze_method_runtime_requirements(program)
    assert requirements.ports == (
        MethodRuntimePort.AGENT_LOOP,
        MethodRuntimePort.CAPABILITIES,
    )
    assert requirements.agent_ids == ("planner",)
    assert requirements.capability_ids == ("env.reset", "env.step")
    assert len(requirements.digest) == 64


def test_hidden_child_machine_requirement_is_explicit_and_fail_fast() -> None:
    program = (
        MethodProgramBuilder(_identity("requirements.child"), entrypoint="return")
        .return_node("return", "return", _finish)
        .build(required_runtime_ports=(MethodRuntimePort.CHILD_MACHINES,))
    )
    requirements = analyze_method_runtime_requirements(program)
    assert requirements.ports == (MethodRuntimePort.CHILD_MACHINES,)
    runtime = MethodRuntimeContext(ExecutionContext("run", "trace", "span"))
    assert requirements.missing_ports(runtime) == (MethodRuntimePort.CHILD_MACHINES,)
    with pytest.raises(RuntimeError, match="child_machines"):
        requirements.require(runtime)


def test_declared_capabilities_require_capability_port_without_capability_node() -> None:
    program = (
        MethodProgramBuilder(_identity("requirements.declared-capability"), entrypoint="return")
        .return_node("return", "return", _finish)
        .build(required_capabilities=("model.generate",))
    )
    requirements = analyze_method_runtime_requirements(program)
    assert requirements.ports == (MethodRuntimePort.CAPABILITIES,)
    assert requirements.capability_ids == ("model.generate",)


def test_non_default_schema_requires_schema_port() -> None:
    program = (
        MethodProgramBuilder(_identity("requirements.schema"), entrypoint="return")
        .return_node("return", "return", _finish)
        .build(input_schema="task.input.v1")
    )
    requirements = analyze_method_runtime_requirements(program)
    assert MethodRuntimePort.SCHEMAS in requirements.ports


def test_runtime_port_declaration_participates_in_program_identity() -> None:
    def build(ports=()):
        return (
            MethodProgramBuilder(_identity("requirements.identity"), entrypoint="return")
            .return_node("return", "return", _finish)
            .build(required_runtime_ports=ports)
        )
    assert build().program_digest != build((MethodRuntimePort.CHILD_MACHINES,)).program_digest
