from __future__ import annotations

import time
from collections.abc import Callable

from noetrium_platform.foundation.kernel.concurrency.api import ExecutionControlPort

from noetrium_platform.foundation.kernel.kernel import ExecutionContext, canonical_digest
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import (
    require_task_unit,
    task_family,
    task_id,
    task_lineage_id,
)
from noetrium_platform.research.execution.api import (
    MethodRunResult,
    MethodRunStatus,
)

from ..api import (
    WorkloadMethodCompilerPort,
    WorkloadMethodReceipt,
    WorkloadMethodResultAdapterPort,
    WorkloadTaskResult,
)


class WorkloadMethodBinding:
    """Bind one task to one NoetriumUnit invocation.

    This object owns no task loop, batch cursor, checkpoint cut or retry policy.
    ExperimentProgram/ResearchRunProgram own execution order and recovery through
    Machine Journal transitions.
    """

    def __init__(
        self,
        *,
        execute_method: Callable[..., MethodRunResult],
        executor_digest: str,
        compiler: WorkloadMethodCompilerPort,
        result_adapter: WorkloadMethodResultAdapterPort,
        clock=time.monotonic,
    ) -> None:
        if not callable(execute_method):
            raise TypeError("workload binding execute_method must be callable")
        if type(executor_digest) is not str or len(executor_digest) != 64:
            raise TypeError(
                "workload Method binding executor requires a stable identity digest"
            )
        if not callable(getattr(compiler, "compile", None)):
            raise TypeError("workload binding compiler must implement compile")
        if not callable(getattr(result_adapter, "evaluate", None)):
            raise TypeError("workload binding result_adapter must implement evaluate")
        if not callable(clock):
            raise TypeError("workload binding clock must be callable")
        compiler_identity = getattr(compiler, "digest", None)
        adapter_identity = getattr(result_adapter, "digest", None)
        for field_name, identity in (
            ("compiler", compiler_identity),
            ("result_adapter", adapter_identity),
        ):
            if type(identity) is not str or len(identity) != 64:
                raise TypeError(
                    f"workload Method binding {field_name} requires a stable identity digest"
                )
        self._execute_method = execute_method
        self._compiler = compiler
        self._result_adapter = result_adapter
        self._clock = clock
        self.identity_digest = canonical_digest({
            "binding": "workload-method-binding.v4",
            "executor": executor_digest,
            "compiler": compiler_identity,
            "result_adapter": adapter_identity,
        })

    def execute_one(
        self,
        task: NoetriumUnit,
        context: ExecutionContext,
        control: ExecutionControlPort,
    ) -> WorkloadTaskResult:
        require_task_unit(task)
        if not isinstance(context, ExecutionContext):
            raise TypeError("workload context must be ExecutionContext")
        invocation = self._compiler.compile(task, context, control)
        started = self._clock()
        result = self._execute_method(
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
            evidence_reference=result.evidence_reference,
            failure_id=result.failure_id,
        )
        diagnostics = dict(evaluation.diagnostics)
        diagnostics.setdefault("method_run_digest", result.run_digest)
        diagnostics.setdefault("method_program_digest", result.program_digest)
        if result.failure_id is not None:
            diagnostics.setdefault("failure_id", result.failure_id)
        return WorkloadTaskResult(
            task_id=task_id(task),
            family=task_family(task),
            lineage_id=task_lineage_id(task),
            complete=result.status is MethodRunStatus.SUCCEEDED,
            success=evaluation.success,
            utility=evaluation.utility,
            steps=result.step_count,
            duration_s=duration,
            failure_reason=evaluation.failure_reason,
            participant_receipts=(("method", receipt),),
            completion_receipt=evaluation.completion_receipt,
            failure_scope=evaluation.failure_scope,
            diagnostics=diagnostics,
            exports=evaluation.exports,
        )


__all__ = ["WorkloadMethodBinding"]
