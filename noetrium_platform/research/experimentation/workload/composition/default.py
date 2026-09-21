from __future__ import annotations

from noetrium_platform.research.execution.workflow.api import MethodMachinePort

from ..api import WorkloadMethodCompilerPort, WorkloadMethodResultAdapterPort, WorkloadTaskExecutionPort
from ..runtime import WorkloadMethodBinding


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


__all__ = ["bind_method_workload"]
