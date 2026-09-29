from __future__ import annotations

from pathlib import Path

from noetrium_platform.composition.method_runtime import (
    standard_method_evidence_factory,
    standard_method_runtime_binder,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodProgram,
    MethodRuntimePortInventory,
)
from noetrium_platform.research.experimentation.workload.api import (
    WorkloadTaskExecutionPort,
)
from noetrium_platform.research.experimentation.workload.composition import (
    DeclarativeExecutionResultAdapter,
    DeclarativeWorkloadMethodCompiler,
    MethodResultProjection,
    TaskFieldProjection,
    bind_method_workload,
    compose_method_runtime_bindings,
)

from .contracts import ReproductionMethodWorkloadBinding


def compose_reproduction_method_workload(
    program: MethodProgram,
    binding: ReproductionMethodWorkloadBinding,
    runtime_inventory: MethodRuntimePortInventory,
    *,
    state_root: str | Path,
) -> WorkloadTaskExecutionPort:
    """Compose one downstream MethodProgram into the canonical workload executor."""

    if not isinstance(program, MethodProgram):
        raise TypeError("reproduction workload composition requires MethodProgram")
    if type(binding) is not ReproductionMethodWorkloadBinding:
        raise TypeError(
            "reproduction workload composition requires ReproductionMethodWorkloadBinding"
        )
    if not isinstance(runtime_inventory, MethodRuntimePortInventory):
        raise TypeError(
            "reproduction workload composition requires MethodRuntimePortInventory"
        )

    runtime = compose_method_runtime_bindings(
        program,
        runtime_inventory,
        runtime_binder=standard_method_runtime_binder(),
        evidence_factory=standard_method_evidence_factory(),
        state_root=Path(state_root),
    )
    compiler = DeclarativeWorkloadMethodCompiler(
        program,
        runtime,
        input_projection=TaskFieldProjection(fields=binding.input_fields),
        initial_state_projection=(
            None
            if not binding.initial_state_fields
            else TaskFieldProjection(fields=binding.initial_state_fields)
        ),
    )
    result_adapter = DeclarativeExecutionResultAdapter(
        MethodResultProjection(fields=binding.result_fields)
    )
    return bind_method_workload(
        compiler=compiler,
        result_adapter=result_adapter,
    )


__all__ = ["compose_reproduction_method_workload"]
