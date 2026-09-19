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
from noetrium_platform.research.execution.workflow.runtime import UniversalMethodMachine
from noetrium_platform.research.experimentation.experiment.api import ExperimentTaskSpec
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


class _Compiler:
    def __init__(self): self.calls = []
    def compile(self, task, context):
        self.calls.append(task.task_id)
        execution = replace(
            context,
            run_id=f"{context.run_id}:{task.task_id}",
            task_id=task.task_id,
            span_id=f"{context.span_id}:{task.task_id}",
        )
        return WorkloadMethodInvocation(
            _program(), MethodRuntimeContext(execution), input_value={"task_id": task.task_id}
        )


class _Evaluator:
    def evaluate(self, task, result):
        assert result.value["ok"] is True
        return WorkloadEvaluation(True, 0.75, diagnostics={"benchmark": "ok"})


def test_workload_binding_executes_one_method_without_owning_a_task_loop():
    compiler = _Compiler()
    binding = WorkloadMethodBinding(
        machine=UniversalMethodMachine(), compiler=compiler, result_adapter=_Evaluator()
    )
    result = binding.execute_one(
        ExperimentTaskSpec("task-1", "family", "objective"),
        ExecutionContext("run", "trace", "span"),
    )
    assert compiler.calls == ["task-1"]
    assert result.success is True
    assert result.utility == 0.75
    assert result.method_receipt is not None
    assert result.method_receipt.run_id == "run:task-1"


class _BadEvaluator:
    def evaluate(self, task, result):
        return WorkloadEvaluation(True, 1.0)


class _FailingMachine:
    def run(self, program, *, runtime, input_value=None, initial_state=None, resume=False):
        def fail(request):
            raise RuntimeError("boom")
        failing = (
            MethodProgramBuilder(program.program_identity, entrypoint="fail")
            .add(MethodNodeSpec("fail", "test.fail", (), fail, kind=MethodNodeKind.RETURN))
            .build()
        )
        return UniversalMethodMachine().run(failing, runtime=runtime)


def test_workload_binding_rejects_success_for_failed_method():
    binding = WorkloadMethodBinding(
        machine=_FailingMachine(), compiler=_Compiler(), result_adapter=_BadEvaluator()
    )
    with pytest.raises(ValueError, match="cannot be evaluated as successful"):
        binding.execute_one(
            ExperimentTaskSpec("task-fail", "family", "objective"),
            ExecutionContext("run", "trace", "span"),
        )
