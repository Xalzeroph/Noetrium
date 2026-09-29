from __future__ import annotations

from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.foundation.kernel.kernel import MachineJournalPort, canonical_digest
from noetrium_platform.research.execution.api import (
    MethodProgramExecutorPort,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.runtime import (
    execute_bound_method_program,
)

from ..api import (
    WorkloadExecutionPort,
    WorkloadMethodCompilerPort,
    WorkloadMethodResultAdapterPort,
    WorkloadTaskExecutionPort,
)
from ..runtime import WorkloadGraphBinding, WorkloadMethodBinding


class _CanonicalMethodProgramExecutor(MethodProgramExecutorPort):
    identity_digest = canonical_digest({
        "executor": "noetrium.canonical-method-program-executor.v1",
    })

    def execute(
        self,
        program,
        *,
        runtime: MethodRuntimeContext,
        input_value=None,
        initial_state=None,
        resume: bool = False,
    ):
        return execute_bound_method_program(
            program,
            runtime=runtime,
            input_value=input_value,
            initial_state=initial_state,
            resume=resume,
        )


_CANONICAL_METHOD_EXECUTOR = _CanonicalMethodProgramExecutor()


def bind_method_workload(
    *,
    compiler: WorkloadMethodCompilerPort,
    result_adapter: WorkloadMethodResultAdapterPort,
) -> WorkloadTaskExecutionPort:
    """Bind generic experiment tasks to the universal ResearchProgram execution path."""

    return WorkloadMethodBinding(
        executor=_CANONICAL_METHOD_EXECUTOR,
        compiler=compiler,
        result_adapter=result_adapter,
    )


def bind_workload_graph(
    workload: WorkloadTaskExecutionPort,
    *,
    journal: MachineJournalPort,
    task_group: TaskGroupPort | None = None,
) -> WorkloadExecutionPort:
    task_group_scope = getattr(workload, "task_group_scope", None)
    if task_group is not None and callable(task_group_scope):
        raise ValueError(
            "workload composition received both explicit and executor-owned task groups"
        )
    return WorkloadGraphBinding(
        workload,
        journal=journal,
        task_group=task_group,
        task_group_scope=(
            task_group_scope if callable(task_group_scope) else None
        ),
    )


__all__ = ["bind_method_workload", "bind_workload_graph"]
