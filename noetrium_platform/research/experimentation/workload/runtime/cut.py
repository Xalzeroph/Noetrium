from __future__ import annotations

from dataclasses import replace

from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.research.experimentation.lifecycle.api import (
    ExperimentTaskSpec,
    FailureScope,
)

from ..api import (
    WorkloadCutExecutionPort,
    WorkloadCutResult,
    WorkloadTaskExecutionPort,
    WorkloadTaskRunError,
)


class SequentialWorkloadCutBinding:
    """Execute one frozen task cut inside one assignment lifetime."""

    def __init__(self, workload: WorkloadTaskExecutionPort) -> None:
        if not callable(getattr(workload, "execute_one", None)):
            raise TypeError("cut binding requires WorkloadTaskExecutionPort")
        self._workload = workload

    def execute_cut(
        self,
        tasks: tuple[ExperimentTaskSpec, ...],
        context: ExecutionContext,
    ) -> WorkloadCutResult:
        if type(tasks) is not tuple or not tasks:
            raise TypeError("cut execution requires a non-empty task tuple")
        if any(not isinstance(task, ExperimentTaskSpec) for task in tasks):
            raise TypeError("cut execution tasks must be ExperimentTaskSpec")
        task_ids = tuple(task.task_id for task in tasks)
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("cut execution task ids must be unique")
        if not isinstance(context, ExecutionContext):
            raise TypeError("cut execution requires ExecutionContext")

        results = []
        for index, task in enumerate(tasks):
            child = replace(
                context,
                span_id=f"{context.span_id}:task:{index:04d}",
                parent_span_id=context.span_id,
                task_id=task.task_id,
                operation_id=(
                    f"{context.operation_id or context.span_id}:task:{index:04d}"
                ),
                component_id="sequential-workload-cut",
            )
            result = self._workload.execute_one(task, child)
            if result.task_id != task.task_id:
                raise ValueError("cut workload result task identity drift")
            results.append(result)
            scope = FailureScope(result.failure_scope)
            if not result.success and scope is not FailureScope.TASK:
                raise WorkloadTaskRunError(
                    "cut",
                    "wider-scope-task-failure",
                    (
                        f"task {task.task_id!r} failed with "
                        f"scope={scope.value}"
                    ),
                    scope=scope,
                )
        return WorkloadCutResult(tuple(results))


__all__ = ["SequentialWorkloadCutBinding"]
