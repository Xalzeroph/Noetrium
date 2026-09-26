from __future__ import annotations

from noetrium_platform.research.execution.api import MethodMachinePort

from ..api import (
    WorkloadCutExecutionPort,
    WorkloadMethodCompilerPort,
    WorkloadMethodResultAdapterPort,
    WorkloadTaskExecutionPort,
)
from ..runtime import SequentialWorkloadCutBinding, WorkloadMethodBinding


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


def bind_sequential_workload_cut(
    workload: WorkloadTaskExecutionPort,
) -> WorkloadCutExecutionPort:
    return SequentialWorkloadCutBinding(workload)


__all__ = ["bind_method_workload", "bind_sequential_workload_cut"]
