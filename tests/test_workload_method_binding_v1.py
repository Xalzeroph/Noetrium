from noetrium_platform.foundation.kernel.kernel import OperationExecutor
from dataclasses import replace

import pytest

from noetrium_platform.capabilities.participant.api import participant_implementation_unit
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.foundation.kernel.concurrency.api import UNBOUNDED_EXECUTION_CONTROL
from noetrium_platform.research.execution.workflow.api import (
    MethodNodeKind,
    MethodNodeResult,
    method_operation,
    method_program,
    MethodRuntimeContext,
    method_program_identity,
)
from noetrium_platform.composition.method_runtime import bind_standard_method_runtime
from noetrium_platform.research.execution.workflow.runtime import (
    KernelOperationDispatcher,
    execute_bound_method_program,
)
from tests_support import task_for_test
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import task_id
from noetrium_platform.research.experimentation.workload.api import (
    WorkloadEvaluation,
    WorkloadMethodInvocation,
)
from noetrium_platform.research.experimentation.workload.runtime import WorkloadMethodBinding


def _workload_finish(request):
    return MethodNodeResult(value={"ok": True, "task": request.input_value})


def _workload_fail(_request):
    raise RuntimeError("boom")


def _program():
    identity = participant_implementation_unit("method", "test.workload.method", "1", "1", "1")
    return method_program(
        identity,
        entrypoint="finish",
        operations=(method_operation(
            "finish", "test.finish",
            kind=MethodNodeKind.RETURN,
            handler=_workload_finish,
        ),),
    )


class _Executor:
    identity_digest = "5" * 64

    def execute(
        self,
        program,
        *,
        runtime,
        input_value=None,
        initial_state=None,
        resume=False,
    ):
        return execute_bound_method_program(
            program,
            runtime=runtime,
            input_value=input_value,
            initial_state=initial_state,
            resume=resume,
        )


class _Compiler:
    digest = "1" * 64

    def __init__(self, state_root):
        self.calls = []
        self.state_root = state_root

    def program_for_task(self, task):
        del task
        return _program()

    def compile(self, task, context, control):
        control.checkpoint()
        self.calls.append(task_id(task))
        execution = replace(
            context,
            run_id=f"{context.run_id}:{task_id(task)}",
            task_id=task_id(task),
            span_id=f"{context.span_id}:{task_id(task)}",
        )
        program = self.program_for_task(task)
        runtime = bind_standard_method_runtime(
            program,
            MethodRuntimeContext(
                execution,
                dispatcher=KernelOperationDispatcher(OperationExecutor()),
            ),
            state_root=self.state_root / task_id(task),
        )
        return WorkloadMethodInvocation(
            program,
            runtime,
            input_value={"task_id": task_id(task)},
        )


class _Evaluator:
    digest = "2" * 64

    def evaluate(self, task, result):
        assert result.value["ok"] is True
        return WorkloadEvaluation(True, 0.75, diagnostics={"benchmark": "ok"})


def test_workload_binding_executes_one_method_without_owning_a_task_loop(tmp_path):
    compiler = _Compiler(tmp_path / "success")
    executor = _Executor()
    binding = WorkloadMethodBinding(
        execute_method=executor.execute,
        executor_digest=executor.identity_digest,
        compiler=compiler,
        result_adapter=_Evaluator(),
    )
    result = binding.execute_one(
        task_for_test("task-1", "family", "objective"),
        ExecutionContext("run", "trace", "span"),
        UNBOUNDED_EXECUTION_CONTROL,
    )
    assert compiler.calls == ["task-1"]
    assert result.success is True
    assert result.utility == 0.75
    assert result.participant_receipts
    role, receipt = result.participant_receipts[0]
    assert role == "method"
    assert receipt.run_id == "run:task-1"


class _BadEvaluator:
    digest = "3" * 64

    def evaluate(self, task, result):
        return WorkloadEvaluation(True, 1.0)


class _FailingCompiler(_Compiler):
    digest = "4" * 64

    def program_for_task(self, task):
        del task

        program = _program()
        return method_program(
            method_program_identity(program),
            entrypoint="fail",
            operations=(method_operation(
                "fail", "test.fail",
                kind=MethodNodeKind.RETURN,
                handler=_workload_fail,
            ),),
        )


def test_workload_binding_rejects_success_for_failed_method(tmp_path):
    executor = _Executor()
    binding = WorkloadMethodBinding(
        execute_method=executor.execute,
        executor_digest=executor.identity_digest,
        compiler=_FailingCompiler(tmp_path / "failed"),
        result_adapter=_BadEvaluator(),
    )
    with pytest.raises(ValueError, match="cannot be evaluated as successful"):
        binding.execute_one(
            task_for_test("task-fail", "family", "objective"),
            ExecutionContext("run", "trace", "span"),
            UNBOUNDED_EXECUTION_CONTROL,
        )
