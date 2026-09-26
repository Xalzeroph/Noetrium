from __future__ import annotations

from noetrium_platform.composition.method_runtime import (
    standard_method_evidence_factory,
    standard_method_runtime_binder,
)


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
    MethodRuntimePortInventory,
    MethodViewChatRequestFactory,
)
from noetrium_platform.research.execution.workflow.runtime import UniversalMethodMachine
from noetrium_platform.research.experimentation.lifecycle.api import ExperimentTaskSpec
from noetrium_platform.research.experimentation.workload.api import WorkloadEvaluation
from noetrium_platform.research.experimentation.workload.composition import (
    DeclarativeExecutionResultAdapter,
    DeclarativeWorkloadMethodCompiler,
    MethodResultProjection,
    MethodRuntimeBindings,
    TaskFieldProjection,
    compose_method_runtime_bindings,
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


def test_method_view_factory_requires_downstream_prompt() -> None:
    factory = MethodViewChatRequestFactory(
        "qwen",
        {"temperature": 0, "max_tokens": 128},
     )
    request = _request(
        "agent-a",
        {
            "instruction": "platform must not synthesize this into a prompt",
            "input": {"task_id": "t1", "objective": "solve"},
        },
    )
    with pytest.raises(ValueError, match="must provide non-empty model-visible prompt"):
        factory.build(request)


def test_method_view_factory_applies_only_explicit_model_generation_namespace() -> None:
    factory = MethodViewChatRequestFactory(
        "qwen",
        {"temperature": 0, "max_tokens": 128},
    )
    request = _request(
        "agent-a",
        {
            "prompt": "Solve exactly.",
            "temperature": 0.99,
            "top_k": 999,
            "model_generation": {
                "temperature": 0.7,
                "top_k": 40,
                "max_tokens": 256,
            },
        },
    )
    body = factory.build(request)
    assert body["temperature"] == 0.7
    assert body["top_k"] == 40
    assert body["max_tokens"] == 256
    assert body["messages"][0]["content"] == "Solve exactly."


def test_method_view_factory_rejects_transport_identity_override() -> None:
    factory = MethodViewChatRequestFactory("qwen", {"temperature": 0})
    request = _request(
        "agent-a",
        {
            "prompt": "x",
            "model_generation": {"model": "different-model"},
        },
    )
    with pytest.raises(ValueError, match="must not override model/messages"):
        factory.build(request)


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
        runtime=MethodRuntimeBindings(
            runtime_binder=standard_method_runtime_binder(),
            evidence_factory=standard_method_evidence_factory(),
            state_root=tmp_path / "state",
        ),
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


def test_auto_composed_declarative_runtime_attaches_only_required_ports(tmp_path: Path) -> None:
    identity = MethodProgramIdentity(MethodIdentity("declarative.agent", "1", "1", "1"))

    def view(request):
        return {"instruction": "return the task id", "input": request.input_value}

    def finish(request):
        return MethodNodeResult(value=request.previous_value)

    program = (
        MethodProgramBuilder(identity, entrypoint="agent")
        .agent("agent", "declarative.agent", "agent-a", ("finish",), view_handler=view)
        .return_node("finish", "declarative.finish", finish)
        .build()
    )
    loop = _Loop("auto")
    router = MethodAgentLoopRouter({"agent-a": loop})
    runtime = compose_method_runtime_bindings(
        program,
        MethodRuntimePortInventory(agent_loop=router),
        runtime_binder=standard_method_runtime_binder(),
        evidence_factory=standard_method_evidence_factory(),
        state_root=tmp_path / "auto-state",
    )
    assert runtime.agent_loop is router
    assert runtime.capabilities is None
    assert runtime.child_machines is None
    assert runtime.schemas is None
    assert runtime.runtime_binding_digest is not None

    compiler = DeclarativeWorkloadMethodCompiler(program=program, runtime=runtime)
    invocation = compiler.compile(
        ExperimentTaskSpec("task-auto", "f", "do it"),
        ExecutionContext("auto-run", "trace", "root"),
    )
    result = UniversalMethodMachine(max_steps=8).run(
        invocation.program,
        runtime=invocation.runtime,
        input_value=invocation.input_value,
    )
    assert result.value == {"agent": "auto"}
    assert loop.calls == ["agent-a"]


def test_declarative_compiler_can_project_task_fields_into_initial_state(
    tmp_path: Path,
) -> None:
    identity = MethodProgramIdentity(
        MethodIdentity("declarative.initial-state", "1", "1", "1")
    )

    def finish(request):
        return MethodNodeResult(
            value={
                "task_id": request.state["task_id"],
                "question": request.state["question"],
                "lane": request.state["lane"],
            }
        )

    program = (
        MethodProgramBuilder(identity, entrypoint="finish")
        .return_node("finish", "declarative.initial-state.finish", finish)
        .build()
    )
    compiler = DeclarativeWorkloadMethodCompiler(
        program=program,
        runtime=MethodRuntimeBindings(
            runtime_binder=standard_method_runtime_binder(),
            evidence_factory=standard_method_evidence_factory(),
            state_root=tmp_path / "state",
        ),
        initial_state_projection=TaskFieldProjection(
            fields=(("task_id", "task_id"), ("question", "objective")),
            constants={"lane": "paper"},
        ),
    )
    invocation = compiler.compile(
        ExperimentTaskSpec("task-1", "qa", "What is 2+2?"),
        ExecutionContext("run", "trace", "root"),
    )
    result = UniversalMethodMachine().run(
        invocation.program,
        runtime=invocation.runtime,
        input_value=invocation.input_value,
        initial_state=invocation.initial_state,
    )
    assert result.value == {
        "task_id": "task-1",
        "question": "What is 2+2?",
        "lane": "paper",
    }
    assert compiler.digest != DeclarativeWorkloadMethodCompiler(
        program=program,
        runtime=compiler.runtime,
    ).digest


def test_declarative_compiler_rejects_two_initial_state_authorities(
    tmp_path: Path,
) -> None:
    program = _program()
    with pytest.raises(ValueError, match="static initial_state or"):
        DeclarativeWorkloadMethodCompiler(
            program=program,
            runtime=MethodRuntimeBindings(
                runtime_binder=standard_method_runtime_binder(),
                evidence_factory=standard_method_evidence_factory(),
                state_root=tmp_path / "state",
            ),
            initial_state={"fixed": True},
            initial_state_projection=TaskFieldProjection(
                fields=(("task_id", "task_id"),),
            ),
        )


def test_declarative_result_adapter_exports_only_declared_method_result_paths() -> None:
    program = _program()
    runtime = MethodRuntimeBindings(
        runtime_binder=standard_method_runtime_binder(),
    )
    compiler = DeclarativeWorkloadMethodCompiler(
        program=program,
        runtime=runtime,
        input_projection=TaskFieldProjection(
            fields=(("task_id", "task_id"), ("objective", "objective")),
        ),
    )
    invocation = compiler.compile(
        ExperimentTaskSpec("task-export", "qa", "question"),
        ExecutionContext("run-export", "trace", "root"),
    )
    result = UniversalMethodMachine().run(
        invocation.program,
        runtime=invocation.runtime,
        input_value=invocation.input_value,
    )
    adapter = DeclarativeExecutionResultAdapter(
        export_projection=MethodResultProjection(
            fields=(("answer", "value.objective"),),
        )
    )
    evaluation = adapter.evaluate(
        ExperimentTaskSpec("task-export", "qa", "question"),
        result,
    )
    assert evaluation.success
    assert evaluation.exports == {"answer": "question"}


def test_task_field_projection_reads_nested_payload_paths() -> None:
    task = ExperimentTaskSpec(
        "task-payload",
        "qa",
        "solve",
        payload={"question": "What is 2+2?", "metadata": {"difficulty": 1}},
    )
    projected = TaskFieldProjection(
        fields=(
            ("task_id", "task_id"),
            ("question", "payload.question"),
            ("difficulty", "payload.metadata.difficulty"),
        ),
    ).project(task)
    assert projected == {
        "task_id": "task-payload",
        "question": "What is 2+2?",
        "difficulty": 1,
    }


def test_task_field_projection_rejects_missing_nested_payload_path() -> None:
    task = ExperimentTaskSpec("task-payload", "qa", "solve", payload={})
    with pytest.raises(KeyError, match="payload.question"):
        TaskFieldProjection(fields=(("question", "payload.question"),)).project(task)
