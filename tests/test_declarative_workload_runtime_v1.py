from __future__ import annotations

from noetrium_platform.composition.method_runtime import (
    standard_method_evidence_factory,
    METHOD_PROGRAM_EXECUTOR_DIGEST,
    execute_standard_method_program,
    METHOD_RUNTIME_BINDER_DIGEST,
    bind_standard_method_runtime,
)
from noetrium_platform.composition.research_execution_content import (
    compose_research_execution_content,
)


from pathlib import Path

from noetrium_platform.foundation.kernel.concurrency.api import UNBOUNDED_EXECUTION_CONTROL

import pytest

from noetrium_platform.capabilities.participant.api import participant_implementation_unit
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    OperationExecutor,
    canonical_digest,
    canonical_text,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodEvent,
    MethodNodeResult,
    MethodRunResult,
    MethodRunStatus,
    MethodNodeKind,
    method_flow_relation,
    method_operation,
    method_program,
)
from noetrium_platform.research.execution.workflow.composition import (
    MethodAgentLoopRouter,
    MethodRuntimePortInventory,
    MethodViewChatRequestFactory,
)
from noetrium_platform.research.execution.workflow.runtime import (
    KernelOperationDispatcher,
    execute_bound_method_program,
)
from tests_support import task_for_test
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import task_id
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


def _declarative_finish(request):
    return MethodNodeResult(
        value={
            "task_id": request.input_value["task_id"],
            "objective": request.input_value["objective"],
        }
    )


def _declarative_agent_view(request):
    return {"instruction": "return the task id", "input": request.input_value}


def _return_previous(request):
    return MethodNodeResult(value=request.previous_value)


def _initial_state_finish(request):
    return MethodNodeResult(
        value={
            "task_id": request.state["task_id"],
            "question": request.state["question"],
            "lane": request.state["lane"],
        }
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


def test_method_view_factory_projects_downstream_owned_view_without_hidden_template() -> None:
    factory = MethodViewChatRequestFactory(
        "qwen",
        {"temperature": 0, "max_tokens": 128},
    )
    view = {
        "instruction": "use exactly the downstream-owned structured view",
        "input": {"task_id": "t1", "objective": "solve"},
    }
    compiled = factory.compile(_request("agent-a", view))
    assert compiled.body["messages"] == (
        {"role": "user", "content": canonical_text(view)},
    )
    assert compiled.compiled_prompt_text == canonical_text(
        compiled.body["messages"]
    )


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
    body = factory.compile(request).body
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
        factory.compile(request).body


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
    identity = participant_implementation_unit("method", "declarative.test", "1", "1", "1")
    return method_program(
        identity,
        entrypoint="finish",
        operations=(method_operation(
            "finish",
            "declarative.finish",
            kind=MethodNodeKind.RETURN,
            handler=_declarative_finish,
        ),),
    )


class _Evaluator:
    digest = canonical_digest({"adapter": "declarative-test-evaluator.v1"})

    def evaluate(self, task, result):
        return WorkloadEvaluation(
            success=result.value["task_id"] == task_id(task),
            utility=1.0,
            diagnostics={"run_id": result.run_id},
        )


def test_declarative_compiler_creates_isolated_machine_and_evidence_per_task(tmp_path: Path) -> None:
    program = _program()
    compiler = DeclarativeWorkloadMethodCompiler(
        program=program,
        runtime=MethodRuntimeBindings(
            bind_runtime=bind_standard_method_runtime,
        runtime_binder_digest=METHOD_RUNTIME_BINDER_DIGEST,
            dispatcher=KernelOperationDispatcher(OperationExecutor()),
            evidence_factory=standard_method_evidence_factory(
                compose_research_execution_content(tmp_path / "content")
            ),
            state_root=tmp_path / "state",
        ),
        input_projection=TaskFieldProjection(
            fields=(("task_id", "task_id"), ("objective", "objective")),
            constants={"lane": "test"},
        ),
    )
    binding = bind_method_workload(
        execute_method=execute_standard_method_program,
        executor_digest=METHOD_PROGRAM_EXECUTOR_DIGEST,
        compiler=compiler,
        result_adapter=_Evaluator(),
    )
    context = ExecutionContext("run", "trace", "root")
    first = binding.execute_one(task_for_test("task-1", "f", "one"), context, UNBOUNDED_EXECUTION_CONTROL)
    second = binding.execute_one(task_for_test("task-2", "f", "two"), context, UNBOUNDED_EXECUTION_CONTROL)
    assert first.success and second.success
    assert first.participant_receipts[0][1].run_id == "run:task-1"
    assert second.participant_receipts[0][1].run_id == "run:task-2"
    assert first.participant_receipts[0][1].evidence_reference is not None
    assert second.participant_receipts[0][1].evidence_reference is not None
    roots = sorted((tmp_path / "state").glob("task-*"))
    assert len(roots) == 2
    assert all(any((root / "machine" / "journal").rglob("*")) for root in roots)
    assert all((root / "evidence").is_dir() for root in roots)
    assert len(compiler.digest) == 64


def test_auto_composed_declarative_runtime_attaches_only_required_ports(tmp_path: Path) -> None:
    identity = participant_implementation_unit("method", "declarative.agent", "1", "1", "1")

    program = method_program(
        identity,
        entrypoint="agent",
        operations=(
            method_operation(
                "agent",
                "declarative.agent",
                kind=MethodNodeKind.AGENT,
                agent_id="agent-a",
                agent_view=_declarative_agent_view,
            ),
            method_operation(
                "finish",
                "declarative.finish",
                kind=MethodNodeKind.RETURN,
                handler=_return_previous,
            ),
        ),
        relations=(method_flow_relation("agent", "finish"),),
    )
    loop = _Loop("auto")
    router = MethodAgentLoopRouter({"agent-a": loop})
    runtime = compose_method_runtime_bindings(
        program,
        MethodRuntimePortInventory(agent_loop=router),
        bind_runtime=bind_standard_method_runtime,
        runtime_binder_digest=METHOD_RUNTIME_BINDER_DIGEST,
        evidence_factory=standard_method_evidence_factory(
            compose_research_execution_content(tmp_path / "content")
        ),
        state_root=tmp_path / "auto-state",
        dispatcher=KernelOperationDispatcher(OperationExecutor()),
    )
    assert runtime.agent_loop is router
    assert runtime.capabilities is None
    assert runtime.unit_activation is None
    assert runtime.schemas is None
    assert runtime.runtime_binding_digest is not None

    compiler = DeclarativeWorkloadMethodCompiler(program=program, runtime=runtime)
    invocation = compiler.compile(
        task_for_test("task-auto", "f", "do it"),
        ExecutionContext("auto-run", "trace", "root"),
        UNBOUNDED_EXECUTION_CONTROL,
    )
    result = execute_bound_method_program(
        invocation.program,
        runtime=invocation.runtime,
        input_value=invocation.input_value,
    )
    assert result.value == {"agent": "auto"}
    assert loop.calls == ["agent-a"]


def test_declarative_compiler_can_project_task_fields_into_initial_state(
    tmp_path: Path,
) -> None:
    identity = participant_implementation_unit("method", "declarative.initial-state", "1", "1", "1")

    program = method_program(
        identity,
        entrypoint="finish",
        operations=(method_operation(
            "finish",
            "declarative.initial-state.finish",
            kind=MethodNodeKind.RETURN,
            handler=_initial_state_finish,
        ),),
    )
    compiler = DeclarativeWorkloadMethodCompiler(
        program=program,
        runtime=MethodRuntimeBindings(
            bind_runtime=bind_standard_method_runtime,
        runtime_binder_digest=METHOD_RUNTIME_BINDER_DIGEST,
            dispatcher=KernelOperationDispatcher(OperationExecutor()),
            evidence_factory=standard_method_evidence_factory(
                compose_research_execution_content(tmp_path / "content")
            ),
            state_root=tmp_path / "state",
        ),
        initial_state_projection=TaskFieldProjection(
            fields=(("task_id", "task_id"), ("question", "objective")),
            constants={"lane": "paper"},
        ),
    )
    invocation = compiler.compile(
        task_for_test("task-1", "qa", "What is 2+2?"),
        ExecutionContext("run", "trace", "root"),
        UNBOUNDED_EXECUTION_CONTROL,
    )
    result = execute_bound_method_program(
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
                bind_runtime=bind_standard_method_runtime,
        runtime_binder_digest=METHOD_RUNTIME_BINDER_DIGEST,
                dispatcher=KernelOperationDispatcher(OperationExecutor()),
                evidence_factory=standard_method_evidence_factory(
                compose_research_execution_content(tmp_path / "content")
            ),
                state_root=tmp_path / "state",
            ),
            initial_state={"fixed": True},
            initial_state_projection=TaskFieldProjection(
                fields=(("task_id", "task_id"),),
            ),
        )


def test_declarative_result_adapter_exports_only_declared_method_result_paths(tmp_path: Path) -> None:
    program = _program()
    runtime = MethodRuntimeBindings(
        bind_runtime=bind_standard_method_runtime,
        runtime_binder_digest=METHOD_RUNTIME_BINDER_DIGEST,
        dispatcher=KernelOperationDispatcher(OperationExecutor()),
        evidence_factory=standard_method_evidence_factory(
            compose_research_execution_content(tmp_path / "content")
        ),
        state_root=tmp_path / "state",
    )
    compiler = DeclarativeWorkloadMethodCompiler(
        program=program,
        runtime=runtime,
        input_projection=TaskFieldProjection(
            fields=(("task_id", "task_id"), ("objective", "objective")),
        ),
    )
    invocation = compiler.compile(
        task_for_test("task-export", "qa", "question"),
        ExecutionContext("run-export", "trace", "root"),
        UNBOUNDED_EXECUTION_CONTROL,
    )
    result = execute_bound_method_program(
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
        task_for_test("task-export", "qa", "question"),
        result,
    )
    assert evaluation.success
    assert evaluation.exports == {"answer": "question"}


def test_task_field_projection_reads_nested_payload_paths() -> None:
    task = task_for_test(
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
    task = task_for_test("task-payload", "qa", "solve", payload={})
    with pytest.raises(KeyError, match="payload.question"):
        TaskFieldProjection(fields=(("question", "payload.question"),)).project(task)


def test_declarative_result_adapter_counts_authoritative_model_invocation_events() -> None:
    result = MethodRunResult(
        MethodRunStatus.SUCCEEDED,
        "run-model-count",
        "a" * 64,
        value={"answer": "42"},
        events=(
            MethodEvent("model.invocation", {
                "request_id": "r1", "input_tokens": 11, "output_tokens": 3,
            }),
            MethodEvent("method.other", {}),
            MethodEvent("capability.evidence", {
                "evidence": {
                    "environment_diagnostics": {"physical_child_effect_count": 4},
                },
            }),
            MethodEvent("model.invocation", {
                "request_id": "r2", "input_tokens": 7, "output_tokens": 5,
            }),
        ),
    )
    evaluation = DeclarativeExecutionResultAdapter().evaluate(
        task_for_test("task-model-count", "qa", "question"),
        result,
    )
    assert evaluation.diagnostics["model_call_count"] == 2
    assert evaluation.diagnostics["model_tokens"] == 26
    assert evaluation.diagnostics["physical_child_effects"] == 4


def test_declarative_compiler_isolates_same_task_across_lifetimes(
    tmp_path: Path,
) -> None:
    program = _program()
    compiler = DeclarativeWorkloadMethodCompiler(
        program=program,
        runtime=MethodRuntimeBindings(
            bind_runtime=bind_standard_method_runtime,
        runtime_binder_digest=METHOD_RUNTIME_BINDER_DIGEST,
            dispatcher=KernelOperationDispatcher(OperationExecutor()),
            evidence_factory=standard_method_evidence_factory(
                compose_research_execution_content(tmp_path / "content")
            ),
            state_root=tmp_path / "state",
        ),
        input_projection=TaskFieldProjection(
            fields=(("task_id", "task_id"), ("objective", "objective")),
        ),
    )
    binding = bind_method_workload(
        execute_method=execute_standard_method_program,
        executor_digest=METHOD_PROGRAM_EXECUTOR_DIGEST,
        compiler=compiler,
        result_adapter=_Evaluator(),
    )
    task = task_for_test("task-1", "f", "one")
    first = binding.execute_one(
        task,
        ExecutionContext(
            "run",
            "trace-a",
            "root-a",
            lifetime_id="assignment-a",
        ),
        UNBOUNDED_EXECUTION_CONTROL,
    )
    second = binding.execute_one(
        task,
        ExecutionContext(
            "run",
            "trace-b",
            "root-b",
            lifetime_id="assignment-b",
        ),
        UNBOUNDED_EXECUTION_CONTROL,
    )
    assert first.success and second.success
    first_method = dict(first.participant_receipts)["method"]
    second_method = dict(second.participant_receipts)["method"]
    assert first_method.run_id != second_method.run_id
    assert ":lifetime:" in first_method.run_id
    lifetime_roots = tuple((tmp_path / "state").glob("lifetime-*"))
    assert len(lifetime_roots) == 2
    assert all(any(root.rglob("*.journal")) for root in lifetime_roots)
