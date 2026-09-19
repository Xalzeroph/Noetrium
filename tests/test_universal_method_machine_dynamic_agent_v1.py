from __future__ import annotations

import pytest

from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
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
        MethodIdentity(name, "1", "noetrium.method-machine.v1", "dynamic-agent.v1")
    )


def _view(request: MethodNodeRequest):
    return {"speaker": request.state["speaker"], "count": request.state.get("count", 0)}


def _target(request: MethodNodeRequest) -> str:
    value = request.state.get("speaker")
    if not isinstance(value, str):
        raise TypeError("speaker must be text")
    return value


def _switch(request: MethodNodeRequest) -> MethodNodeResult:
    count = request.state.get("count", 0)
    if type(count) is not int:
        raise TypeError("count must be int")
    if count == 0:
        return MethodNodeResult(
            value={"next": "b"},
            state_update={"speaker": "b", "count": 1},
            next_node="agent",
        )
    return MethodNodeResult(value={"done": True}, next_node="return")


def _finish(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(
        value={
            "speaker": request.state["speaker"],
            "count": request.state["count"],
        }
    )


def _program(agent_ids: tuple[str, ...]) -> MethodProgram:
    builder = MethodProgramBuilder(_identity("dynamic-speaker"), entrypoint="agent")
    builder.dynamic_agent(
        "agent",
        "dynamic-speaker.invoke",
        agent_ids,
        _target,
        ("switch",),
        view_handler=_view,
        max_visits=2,
    )
    builder.route(
        "switch",
        "dynamic-speaker.route",
        _switch,
        ("agent", "return"),
        max_visits=2,
    )
    builder.return_node("return", "dynamic-speaker.return", _finish)
    return builder.build()


class _AgentLoop:
    def __init__(self) -> None:
        self.agent_ids: list[str] = []
        self.views: list[object] = []

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        self.agent_ids.append(request.agent_id)
        self.views.append(request.view)
        return MethodAgentResult(value={"speaker": request.agent_id})


def _context() -> ExecutionContext:
    return ExecutionContext("run-1", "trace-1", "span-1")


def test_dynamic_agent_selects_from_frozen_participant_closure() -> None:
    loop = _AgentLoop()
    result = UniversalMethodMachine().run(
        _program(("a", "b")),
        runtime=MethodRuntimeContext(_context(), agent_loop=loop),
        initial_state={"speaker": "a", "count": 0},
    )

    assert result.status is MethodRunStatus.SUCCEEDED
    assert loop.agent_ids == ["a", "b"]
    assert loop.views == [
        {"speaker": "a", "count": 0},
        {"speaker": "b", "count": 1},
    ]
    assert result.value == {"speaker": "b", "count": 1}


def test_dynamic_agent_rejects_target_outside_frozen_closure() -> None:
    with pytest.raises(ValueError, match="undeclared participant"):
        UniversalMethodMachine().run(
            _program(("a", "b")),
            runtime=MethodRuntimeContext(_context(), agent_loop=_AgentLoop()),
            initial_state={"speaker": "c", "count": 0},
        )


def test_dynamic_agent_target_closure_changes_graph_identity() -> None:
    left = _program(("a", "b"))
    right = _program(("a", "c"))

    assert left.graph.graph_digest != right.graph.graph_digest
    assert left.program_digest != right.program_digest
