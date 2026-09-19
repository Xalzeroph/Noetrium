from __future__ import annotations

import time

from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.research.execution.workflow.api import MethodMachinePort, MethodRunStatus
from noetrium_platform.research.experimentation.experiment.api import ExperimentTaskSpec

from ..api import (
    WorkloadMethodCompilerPort,
    WorkloadMethodReceipt,
    WorkloadMethodResultAdapterPort,
    WorkloadTaskResult,
)


class WorkloadMethodBinding:
    """Bind one task to one MethodProgram invocation.

    This object owns no task loop, batch cursor, checkpoint cut or retry policy.
    ExperimentProgram/ResearchRunProgram own execution order and recovery through
    Machine Journal transitions.
    """

    def __init__(
        self,
        *,
        machine: MethodMachinePort,
        compiler: WorkloadMethodCompilerPort,
        result_adapter: WorkloadMethodResultAdapterPort,
        clock=time.monotonic,
    ) -> None:
        if not callable(getattr(machine, "run", None)):
            raise TypeError("workload binding machine must implement MethodMachinePort.run")
        if not callable(getattr(compiler, "compile", None)):
            raise TypeError("workload binding compiler must implement compile")
        if not callable(getattr(result_adapter, "evaluate", None)):
            raise TypeError("workload binding result_adapter must implement evaluate")
        if not callable(clock):
            raise TypeError("workload binding clock must be callable")
        self._machine = machine
        self._compiler = compiler
        self._result_adapter = result_adapter
        self._clock = clock

    def execute_one(
        self,
        task: ExperimentTaskSpec,
        context: ExecutionContext,
    ) -> WorkloadTaskResult:
        if not isinstance(task, ExperimentTaskSpec):
            raise TypeError("workload task must be ExperimentTaskSpec")
        if not isinstance(context, ExecutionContext):
            raise TypeError("workload context must be ExecutionContext")
        invocation = self._compiler.compile(task, context)
        started = self._clock()
        result = self._machine.run(
            invocation.program,
            runtime=invocation.runtime,
            input_value=invocation.input_value,
            initial_state=invocation.initial_state,
            resume=invocation.resume,
        )
        duration = self._clock() - started
        evaluation = self._result_adapter.evaluate(task, result)
        if result.status is not MethodRunStatus.SUCCEEDED and evaluation.success:
            raise ValueError("failed/interrupted method run cannot be evaluated as successful")
        receipt = WorkloadMethodReceipt(
            run_id=result.run_id,
            program_digest=result.program_digest,
            run_digest=result.run_digest,
            status=result.status.value,
            step_count=result.step_count,
            evidence_status=result.evidence_status.value,
        )
        diagnostics = dict(evaluation.diagnostics)
        diagnostics.setdefault("method_run_digest", result.run_digest)
        diagnostics.setdefault("method_program_digest", result.program_digest)
        return WorkloadTaskResult(
            task_id=task.task_id,
            family=task.family,
            lineage_id=task.lineage_id,
            success=evaluation.success,
            utility=evaluation.utility,
            steps=result.step_count,
            duration_s=duration,
            failure_reason=evaluation.failure_reason,
            method_receipt=receipt,
            completion_receipt=evaluation.completion_receipt,
            failure_scope=evaluation.failure_scope,
            diagnostics=diagnostics,
        )


__all__ = ["WorkloadMethodBinding"]
