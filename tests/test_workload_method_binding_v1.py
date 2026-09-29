from noetrium_platform.foundation.kernel.kernel import OperationExecutor
from dataclasses import replace

import pytest

from noetrium_platform.capabilities.participant.method.api import MethodIdentity, MethodProgramIdentity
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.research.execution.workflow.api import (
    MethodNodeKind,
    MethodNodeResult,
    MethodNodeSpec,
    MethodProgramBuilder,
    MethodRuntimeContext,
)
from noetrium_platform.composition.method_runtime import bind_standard_method_runtime
from noetrium_platform.research.execution.workflow.runtime import (
    KernelOperationDispatcher,
    execute_bound_method_program,
)
from noetrium_platform.research.experimentation.lifecycle.api import ExperimentTaskSpec
from noetrium_platform.research.experimentation.workload.api import (
    WorkloadEvaluation,
    WorkloadMethodInvocation,
)
from noetrium_platform.research.experimentation.workload.runtime import WorkloadMethodBinding


def _program():
    identity = MethodProgramIdentity(MethodIdentity("test.workload.method", "1", "1", "1"))
    def finish(request):
        return MethodNodeResult(value={"ok": True, "task": request.input_value})
    return (
        MethodProgramBuilder(identity, entrypoint="finish")
        .add(MethodNodeSpec("finish", "test.finish", (), finish, kind=MethodNodeKind.RETURN))
        .build()
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

    def compile(self, task, context):
        self.calls.append(task.task_id)
        execution = replace(
            context,
            run_id=f"{context.run_id}:{task.task_id}",
            task_id=task.task_id,
            span_id=f"{context.span_id}:{task.task_id}",
        )
        program = self.program_for_task(task)
        runtime = bind_standard_method_runtime(
            program,
            MethodRuntimeContext(
                execution,
                dispatcher=KernelOperationDispatcher(OperationExecutor()),
            ),
            state_root=self.state_root / task.task_id,
        )
        return WorkloadMethodInvocation(
            program,
            runtime,
            input_value={"task_id": task.task_id},
        )


class _Evaluator:
    digest = "2" * 64

    def evaluate(self, task, result):
        assert result.value["ok"] is True
        return WorkloadEvaluation(True, 0.75, diagnostics={"benchmark": "ok"})


def test_workload_binding_executes_one_method_without_owning_a_task_loop(tmp_path):
    compiler = _Compiler(tmp_path / "success")
    binding = WorkloadMethodBinding(
        executor=_Executor(),
        compiler=compiler,
        result_adapter=_Evaluator(),
    )
    result = binding.execute_one(
        ExperimentTaskSpec("task-1", "family", "objective"),
        ExecutionContext("run", "trace", "span"),
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

        def fail(request):
            raise RuntimeError("boom")

        program = _program()
        return (
            MethodProgramBuilder(program.program_identity, entrypoint="fail")
            .add(
                MethodNodeSpec(
                    "fail",
                    "test.fail",
                    (),
                    fail,
                    kind=MethodNodeKind.RETURN,
                )
            )
            .build()
        )


def test_workload_binding_rejects_success_for_failed_method(tmp_path):
    binding = WorkloadMethodBinding(
        executor=_Executor(),
        compiler=_FailingCompiler(tmp_path / "failed"),
        result_adapter=_BadEvaluator(),
    )
    with pytest.raises(ValueError, match="cannot be evaluated as successful"):
        binding.execute_one(
            ExperimentTaskSpec("task-fail", "family", "objective"),
            ExecutionContext("run", "trace", "span"),
        )
