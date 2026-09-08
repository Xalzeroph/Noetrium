from __future__ import annotations

import math

from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentTaskSpec,
    ExperimentWorkloadFailure,
    FailureScope,
    validate_task_graph,
)

from ..api import (
    WorkloadBatchBindingPort,
    WorkloadBatchCloseError,
    WorkloadBatchExecutorPort,
    WorkloadBatchResult,
    WorkloadExecutionCutObserverPort,
    WorkloadTaskResult,
)


def _require_prior_prefix(
    tasks: tuple[ExperimentTaskSpec, ...],
    prior_results: tuple[WorkloadTaskResult, ...],
) -> None:
    task_ids = tuple(task.task_id for task in tasks)
    prior_ids = tuple(result.task_id for result in prior_results)
    if prior_ids != task_ids[: len(prior_ids)]:
        raise ValueError(
            "workload resume results must be an exact prefix of the validated task graph"
        )
    if len(set(prior_ids)) != len(prior_ids):
        raise ValueError("workload resume results contain duplicate task ids")
    for result in prior_results:
        _require_valid_result(result, prefix="workload resume result is invalid")


def _require_valid_result(result: WorkloadTaskResult, *, prefix: str) -> None:
    if not math.isfinite(float(result.utility)) or result.steps < 0:
        raise ValueError(f"{prefix}: {result.task_id}")


def _failed_dependencies(
    task: ExperimentTaskSpec,
    by_id: dict[str, WorkloadTaskResult],
) -> tuple[str, ...]:
    return tuple(
        dependency
        for dependency in task.depends_on_task_ids
        if dependency in by_id and not by_id[dependency].success
    )


def _blocked_result(
    task: ExperimentTaskSpec,
    failed_dependencies: tuple[str, ...],
) -> WorkloadTaskResult:
    return WorkloadTaskResult(
        task_id=task.task_id,
        family=task.family,
        lineage_id=task.lineage_id,
        success=False,
        utility=0.0,
        steps=0,
        duration_s=0.0,
        failure_reason="blocked_dependency",
        blocked=True,
        diagnostics={"blocked_by": failed_dependencies},
    )


def _task_failure_result(
    task: ExperimentTaskSpec,
    exc: ExperimentWorkloadFailure,
) -> WorkloadTaskResult:
    return WorkloadTaskResult(
        task_id=task.task_id,
        family=task.family,
        lineage_id=task.lineage_id,
        success=False,
        utility=0.0,
        steps=0,
        duration_s=0.0,
        failure_reason=exc.code,
        failure_scope=exc.scope.value,
        diagnostics={
            "phase": exc.phase,
            "failure_scope": exc.scope.value,
            "error_type": type(exc).__name__,
            "error": str(exc),
        },
    )


def _execute_task(
    binding: WorkloadBatchBindingPort,
    task: ExperimentTaskSpec,
    by_id: dict[str, WorkloadTaskResult],
) -> WorkloadTaskResult:
    failed_dependencies = _failed_dependencies(task, by_id)
    if failed_dependencies:
        return _blocked_result(task, failed_dependencies)
    try:
        return binding.runner_for(task).run(task, binding.context)
    except ExperimentWorkloadFailure as exc:
        if exc.scope is not FailureScope.TASK:
            raise
        return _task_failure_result(task, exc)


class GenericWorkloadBatchExecutor(WorkloadBatchExecutorPort):
    """Execute a validated task DAG with O(V+E) scheduling work."""

    def __init__(self, cut_observer: WorkloadExecutionCutObserverPort | None = None) -> None:
        self._cut_observer = cut_observer

    def execute(
        self,
        binding: WorkloadBatchBindingPort,
        *,
        prior_results: tuple[WorkloadTaskResult, ...] = (),
        cut_observer: WorkloadExecutionCutObserverPort | None = None,
    ) -> WorkloadBatchResult:
        tasks = validate_task_graph(tuple(binding.tasks))
        _require_prior_prefix(tasks, prior_results)
        by_id = {result.task_id: result for result in prior_results}
        results = list(prior_results)
        primary_error: BaseException | None = None
        try:
            self._execute_suffix(
                binding, tasks, prior_results, by_id, results,
                cut_observer if cut_observer is not None else self._cut_observer,
            )
        except BaseException as exc:
            primary_error = exc

        self._close(binding, primary_error)
        if primary_error is not None:
            raise primary_error
        return WorkloadBatchResult(tuple(results))

    def _execute_suffix(
        self,
        binding: WorkloadBatchBindingPort,
        tasks: tuple[ExperimentTaskSpec, ...],
        prior_results: tuple[WorkloadTaskResult, ...],
        by_id: dict[str, WorkloadTaskResult],
        results: list[WorkloadTaskResult],
        cut_observer: WorkloadExecutionCutObserverPort | None,
    ) -> None:
        for task in tasks[len(prior_results) :]:
            result = _execute_task(binding, task, by_id)
            _require_valid_result(result, prefix="workload task result is invalid")
            binding.record_result(task=task, result=result, context=binding.context)
            results.append(result)
            by_id[task.task_id] = result
            if cut_observer is not None:
                cut_observer.after_task(
                    task=task,
                    result=result,
                    context=binding.context,
                )

    @staticmethod
    def _close(
        binding: WorkloadBatchBindingPort,
        primary_error: BaseException | None,
    ) -> None:
        try:
            binding.close()
        except BaseException as exc:
            if primary_error is not None:
                raise WorkloadBatchCloseError(primary_error, exc) from primary_error
            raise


__all__ = [
    "GenericWorkloadBatchExecutor",
    "WorkloadBatchCloseError",
    "WorkloadBatchResult",
]
