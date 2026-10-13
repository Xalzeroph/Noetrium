from __future__ import annotations

from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.foundation.kernel.kernel import MachineJournalPort
from noetrium_platform.research.execution.api import MethodRunResult
from collections.abc import Callable

from ..api import (
    WorkloadExecutionPort,
    WorkloadMethodCompilerPort,
    WorkloadMethodResultAdapterPort,
    WorkloadTaskExecutionPort,
)
from ..runtime import WorkloadGraphBinding, WorkloadMethodBinding


def bind_method_workload(
    *,
    execute_method: Callable[..., MethodRunResult],
    executor_digest: str,
    compiler: WorkloadMethodCompilerPort,
    result_adapter: WorkloadMethodResultAdapterPort,
) -> WorkloadTaskExecutionPort:
    """Bind generic experiment tasks to the universal NoetriumUnit execution path."""

    return WorkloadMethodBinding(
        execute_method=execute_method,
        executor_digest=executor_digest,
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
