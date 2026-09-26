from __future__ import annotations

from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.research.execution.api import MethodMachinePort

from ..api import (
    WorkloadGraphExecutionPort,
    WorkloadMethodCompilerPort,
    WorkloadMethodResultAdapterPort,
    WorkloadTaskExecutionPort,
)
from ..runtime import WorkloadGraphBinding, WorkloadMethodBinding


def bind_method_workload(
    *,
    machine: MethodMachinePort,
    compiler: WorkloadMethodCompilerPort,
    result_adapter: WorkloadMethodResultAdapterPort,
) -> WorkloadTaskExecutionPort:
    """Bind generic experiment tasks to the shared MethodMachine execution path."""

    return WorkloadMethodBinding(
        machine=machine,
        compiler=compiler,
        result_adapter=result_adapter,
    )


def bind_workload_graph(
    workload: WorkloadTaskExecutionPort,
    *,
    task_group: TaskGroupPort | None = None,
) -> WorkloadGraphExecutionPort:
    return WorkloadGraphBinding(
        workload,
        task_group=task_group,
    )


__all__ = ["bind_method_workload", "bind_workload_graph"]
