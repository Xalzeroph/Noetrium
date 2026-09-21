from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.capabilities.participant.method.api import MethodIdentity, MethodProgramIdentity
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    canonical_digest,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodNodeResult,
    MethodProgramBuilder,
)
from noetrium_platform.research.execution.workflow.composition import (
    MethodAgentLoopRouter,
    StructuredViewChatRequestFactory,
)
from noetrium_platform.research.execution.workflow.runtime import UniversalMethodMachine
from noetrium_platform.research.experimentation.experiment.api import ExperimentTaskSpec
from noetrium_platform.research.experimentation.workload.api import WorkloadEvaluation
from noetrium_platform.research.experimentation.workload.composition import (
    DeclarativeWorkloadMethodCompiler,
    MethodRuntimeBindings,
    TaskFieldProjection,
    bind_method_workload,
)


class _Loop:
    def __init__(self, name: str) -> None:
        self.name = name
        self.identity_digest = canonical_digest({"loop": name})
        self.calls: list[str] = []

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        self.calls.append(request.agent_id)
        return MethodAgentResult(value={"agent": self.name})


def _request(agent_id: str, view) -> MethodAgentRequest:
    return MethodAgentRequest(
        agent_id=agent_id,
        goal=None,
        view=view,
        input_value=None,
        previous_value=None,
        context=ExecutionContext(
            "run",
            "trace",
            "span",
            operation_id="operation:1",
        ),
    )


def test_structured_view_factory_is_deterministic_and_keeps_generation_options() -> None:
    factory = StructuredViewChatRequestFactory(
        "qwen",
        {"temperature": 0, "max_tokens": 128},
        system_instruction="Follow the method phase exactly.",
    )
    request = _request(
        "agent-a",
        {
            "instruction": "Inspect the task and propose one action.",
            "input": {"task_id": "t1", "objective": "solve"},
            "state": {"turn": 0},
        },
    )
    first = factory.build(request)
    second = factory.build(request)
    assert first == second
    prompt = first["messages"][0]["content"]
    assert "Follow the method phase exactly." in prompt
    assert "Inspect the task and propose one action." in prompt
    assert '"task_id":"t1"' in prompt
    assert first["temperature"] == 0
    assert len(factory.digest) == 64


def test_method_agent_router_routes_exact_identity_and_fails_closed() -> None:
    left = _Loop("left")
    right = _Loop("right")
    router = MethodAgentLoopRouter({"agent-a": left, "agent-b": right})
    assert router.run(_request("agent-b", {"prompt": "x"})).value["agent"] == "right"
    assert right.calls == ["agent-b"]
    assert left.calls == []
    assert len(router.identity_digest) == 64
    with pytest.raises(KeyError, match="no method agent binding"):
        router.run(_request("missing", {"prompt": "x"}))


def _program():
    identity = MethodProgramIdentity(MethodIdentity("declarative.test", "1", "1", "1"))

    def finish(request):
        return MethodNodeResult(
            value={
                "task_id": request.input_value["task_id"],
                "objective": request.input_value["objective"],
            }
        )

    return MethodProgramBuilder(identity, entrypoint="finish").return_node(
        "finish", "declarative.finish", finish
    ).build()


class _Evaluator:
    def evaluate(self, task, result):
        return WorkloadEvaluation(
            success=result.value["task_id"] == task.task_id,
            utility=1.0,
            diagnostics={"run_id": result.run_id},
        )


def test_declarative_compiler_creates_isolated_machine_and_evidence_per_task(tmp_path: Path) -> None:
    program = _program()
    compiler = DeclarativeWorkloadMethodCompiler(
        program=program,
        runtime=MethodRuntimeBindings(state_root=tmp_path / "state"),
        input_projection=TaskFieldProjection(
            fields=(("task_id", "task_id"), ("objective", "objective")),
            constants={"lane": "test"},
        ),
    )
    binding = bind_method_workload(
        machine=UniversalMethodMachine(),
        compiler=compiler,
        result_adapter=_Evaluator(),
    )
    context = ExecutionContext("run", "trace", "root")
    first = binding.execute_one(ExperimentTaskSpec("task-1", "f", "one"), context)
    second = binding.execute_one(ExperimentTaskSpec("task-2", "f", "two"), context)
    assert first.success and second.success
    assert first.method_receipt.run_id == "run:task-1"
    assert second.method_receipt.run_id == "run:task-2"
    roots = sorted((tmp_path / "state").glob("task-*"))
    assert len(roots) == 2
    assert all(any((root / "machine" / "journal").rglob("*")) for root in roots)
    assert all(list((root / "evidence" / "results").glob("*.json")) for root in roots)
    assert len(compiler.digest) == 64
