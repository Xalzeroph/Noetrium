from __future__ import annotations

from dataclasses import replace

from noetrium_platform.foundation.kernel.concurrency.api import (
    Deadline,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskFailureScope,
    TaskGroupPort,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.research.experimentation.lifecycle.api import (
    AssignmentWorkload,
    ExperimentTaskSpec,
    FailureScope,
)

from ..api import (
    WorkloadGraphExecutionPort,
    WorkloadGraphResult,
    WorkloadTaskExecutionPort,
    WorkloadTaskResult,
    WorkloadTaskRunError,
)


class WorkloadGraphBinding:
    """Execute any immutable assignment workload graph through one task primitive."""

    def __init__(
        self,
        workload: WorkloadTaskExecutionPort,
        *,
        task_group: TaskGroupPort | None = None,
    ) -> None:
        if not callable(getattr(workload, "execute_one", None)):
            raise TypeError(
                "workload graph binding requires WorkloadTaskExecutionPort"
            )
        if task_group is not None and not callable(
            getattr(task_group, "submit", None)
        ):
            raise TypeError("workload graph task_group must satisfy TaskGroupPort")
        self._workload = workload
        self._task_group = task_group

    @staticmethod
    def _child_context(
        context: ExecutionContext,
        task: ExperimentTaskSpec,
        ordinal: int,
    ) -> ExecutionContext:
        return replace(
            context,
            span_id=f"{context.span_id}:task:{ordinal:04d}",
            parent_span_id=context.span_id,
            task_id=task.task_id,
            operation_id=(
                f"{context.operation_id or context.span_id}:task:{ordinal:04d}"
            ),
            component_id="workload-graph",
        )

    def _execute_ready(
        self,
        ready: tuple[ExperimentTaskSpec, ...],
        context: ExecutionContext,
        ordinal_by_id: dict[str, int],
    ) -> tuple[WorkloadTaskResult, ...]:
        if len(ready) <= 1 or self._task_group is None:
            return tuple(
                self._workload.execute_one(
                    task,
                    self._child_context(
                        context,
                        task,
                        ordinal_by_id[task.task_id],
                    ),
                )
                for task in ready
            )

        handles = tuple(
            self._task_group.submit(
                ExecutionSpec(
                    task_id=(
                        f"workload:{context.lifetime_id or context.run_id}:"
                        f"{task.task_id}"
                    ),
                    lane_kind=ExecutionLaneKind.BLOCKING_IO,
                    failure_scope=TaskFailureScope.CALLER,
                ),
                lambda _task_context, owned=task: self._workload.execute_one(
                    owned,
                    self._child_context(
                        context,
                        owned,
                        ordinal_by_id[owned.task_id],
                    ),
                ),
                deadline=Deadline.after(float(task.max_seconds)),
            )
            for task in ready
        )
        values: list[WorkloadTaskResult] = []
        errors: list[BaseException] = []
        for task, handle in zip(ready, handles, strict=True):
            try:
                value = handle.result(timeout=float(task.max_seconds))
                if not isinstance(value, WorkloadTaskResult):
                    raise TypeError(
                        "workload graph task executor returned invalid result"
                    )
                values.append(value)
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise ExceptionGroup("workload graph ready-set execution failed", errors)
        return tuple(values)

    @staticmethod
    def _blocked_result(
        task: ExperimentTaskSpec,
        failed_dependencies: tuple[str, ...],
    ) -> WorkloadTaskResult:
        return WorkloadTaskResult(
            task_id=task.task_id,
            family=task.family,
            success=False,
            utility=0.0,
            steps=0,
            duration_s=0.0,
            lineage_id=task.lineage_id,
            failure_reason=(
                "blocked by failed workload dependencies: "
                + ", ".join(failed_dependencies)
            ),
            blocked=True,
            failure_scope=FailureScope.TASK.value,
            diagnostics={
                "failed_dependencies": failed_dependencies,
                "blocked_by_workload_graph": True,
            },
        )

    def execute_graph(
        self,
        tasks: tuple[ExperimentTaskSpec, ...],
        workload: AssignmentWorkload,
        context: ExecutionContext,
    ) -> WorkloadGraphResult:
        if type(tasks) is not tuple or not tasks:
            raise TypeError(
                "workload graph execution requires a non-empty task tuple"
            )
        if any(not isinstance(task, ExperimentTaskSpec) for task in tasks):
            raise TypeError(
                "workload graph execution tasks must be ExperimentTaskSpec"
            )
        if type(workload) is not AssignmentWorkload:
            raise TypeError(
                "workload graph execution requires AssignmentWorkload"
            )
        if not isinstance(context, ExecutionContext):
            raise TypeError(
                "workload graph execution requires ExecutionContext"
            )

        by_id = {task.task_id: task for task in tasks}
        if len(by_id) != len(tasks):
            raise ValueError("workload graph task ids must be unique")
        if set(by_id) != set(workload.task_ids):
            raise ValueError(
                "workload graph task projection does not match assignment workload"
            )

        ordinal_by_id = {
            task_id: index
            for index, task_id in enumerate(workload.task_ids)
        }
        pending = set(workload.task_ids)
        results: dict[str, WorkloadTaskResult] = {}

        while pending:
            changed = False

            for task_id in tuple(sorted(pending)):
                dependencies = workload.dependencies_for(task_id)
                failed = tuple(
                    dependency
                    for dependency in dependencies
                    if dependency in results
                    and not results[dependency].success
                )
                if failed:
                    results[task_id] = self._blocked_result(
                        by_id[task_id],
                        failed,
                    )
                    pending.remove(task_id)
                    changed = True

            ready_ids = tuple(
                task_id
                for task_id in sorted(pending)
                if all(
                    dependency in results
                    and results[dependency].success
                    for dependency in workload.dependencies_for(task_id)
                )
            )
            if ready_ids:
                ready = tuple(by_id[task_id] for task_id in ready_ids)
                ready_results = self._execute_ready(
                    ready,
                    context,
                    ordinal_by_id,
                )
                for task, result in zip(ready, ready_results, strict=True):
                    if result.task_id != task.task_id:
                        raise ValueError(
                            "workload graph result task identity drift"
                        )
                    scope = FailureScope(result.failure_scope)
                    if not result.success and scope is not FailureScope.TASK:
                        raise WorkloadTaskRunError(
                            "graph",
                            "wider-scope-task-failure",
                            (
                                f"task {task.task_id!r} failed with "
                                f"scope={scope.value}"
                            ),
                            scope=scope,
                        )
                    results[task.task_id] = result
                    pending.remove(task.task_id)
                    changed = True

            if not changed:
                raise RuntimeError(
                    "workload graph made no progress despite validated DAG"
                )

        return WorkloadGraphResult(
            tuple(results[task_id] for task_id in workload.task_ids)
        )


__all__ = ["WorkloadGraphBinding"]
