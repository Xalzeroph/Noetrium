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


def _run(
    capability: str,
    *,
    context: ExecutionContext | None = None,
):
    port = _Capabilities()
    result = UniversalMethodMachine().run(
        _program(("tool.read", "tool.write")),
        runtime=MethodRuntimeContext(
            context or ExecutionContext("run", "trace", "span"),
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


def test_method_node_identity_is_scoped_by_semantic_execution() -> None:
    program = _program(("tool.read", "tool.write"))
    machine = UniversalMethodMachine()
    first = ExecutionContext(
        "run",
        "trace-a",
        "span-a",
        study_id="study",
        lifetime_id="lifetime",
        branch_id="branch-a",
        task_id="task-a",
    )
    replay = ExecutionContext(
        "run",
        "trace-b",
        "span-b",
        study_id="study",
        lifetime_id="lifetime",
        branch_id="branch-a",
        task_id="task-a",
    )
    other_task = ExecutionContext(
        "run",
        "trace-c",
        "span-c",
        study_id="study",
        lifetime_id="lifetime",
        branch_id="branch-a",
        task_id="task-b",
    )

    first_operation = machine._operation_id(first, program, "invoke", 0)
    replay_operation = machine._operation_id(replay, program, "invoke", 0)
    other_task_operation = machine._operation_id(
        other_task,
        program,
        "invoke",
        0,
    )
    first_key = machine._node_idempotency_key(
        first,
        program,
        "invoke",
        0,
    )
    replay_key = machine._node_idempotency_key(
        replay,
        program,
        "invoke",
        0,
    )
    other_task_key = machine._node_idempotency_key(
        other_task,
        program,
        "invoke",
        0,
    )

    assert first_operation == replay_operation
    assert first_key == replay_key
    assert first_operation != other_task_operation
    assert first_key != other_task_key


def test_effectful_capability_idempotency_is_scoped_by_semantic_execution() -> None:
    first_result, first = _run(
        "tool.write",
        context=ExecutionContext(
            "run",
            "trace-a",
            "span-a",
            study_id="study",
            lifetime_id="lifetime",
            branch_id="branch-a",
            task_id="task-a",
        ),
    )
    replay_result, replay = _run(
        "tool.write",
        context=ExecutionContext(
            "run",
            "trace-b",
            "span-b",
            study_id="study",
            lifetime_id="lifetime",
            branch_id="branch-a",
            task_id="task-a",
        ),
    )
    other_task_result, other_task = _run(
        "tool.write",
        context=ExecutionContext(
            "run",
            "trace-c",
            "span-c",
            study_id="study",
            lifetime_id="lifetime",
            branch_id="branch-a",
            task_id="task-b",
        ),
    )
    other_branch_result, other_branch = _run(
        "tool.write",
        context=ExecutionContext(
            "run",
            "trace-d",
            "span-d",
            study_id="study",
            lifetime_id="lifetime",
            branch_id="branch-b",
            task_id="task-a",
        ),
    )

    assert first_result.status is MethodRunStatus.SUCCEEDED
    assert replay_result.status is MethodRunStatus.SUCCEEDED
    assert other_task_result.status is MethodRunStatus.SUCCEEDED
    assert other_branch_result.status is MethodRunStatus.SUCCEEDED

    first_key = first.requests[0].idempotency_key
    replay_key = replay.requests[0].idempotency_key
    other_task_key = other_task.requests[0].idempotency_key
    other_branch_key = other_branch.requests[0].idempotency_key

    assert first_key is not None
    assert first_key == replay_key
    assert first_key != other_task_key
    assert first_key != other_branch_key


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
