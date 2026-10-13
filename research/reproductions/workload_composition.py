from __future__ import annotations

from pathlib import Path

from noetrium_platform.composition.method_runtime import (
    METHOD_PROGRAM_EXECUTOR_DIGEST,
    METHOD_RUNTIME_BINDER_DIGEST,
    bind_standard_method_runtime,
    execute_standard_method_program,
    standard_method_evidence_factory,
)
from noetrium_platform.composition.research_execution_content import (
    ResearchExecutionContentAuthorities,
)

from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.research.execution.api import OperationDispatchPort
from noetrium_platform.research.execution.workflow.api import (
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
    program: NoetriumUnit,
    binding: ReproductionMethodWorkloadBinding,
    runtime_inventory: MethodRuntimePortInventory,
    *,
    content: ResearchExecutionContentAuthorities,
    state_root: str | Path,
    dispatcher: OperationDispatchPort,
) -> WorkloadTaskExecutionPort:
    """Compose one downstream method Unit into the canonical workload executor."""

    if type(program) is not NoetriumUnit:
        raise TypeError("reproduction workload composition requires NoetriumUnit")
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
        bind_runtime=bind_standard_method_runtime,
        runtime_binder_digest=METHOD_RUNTIME_BINDER_DIGEST,
        evidence_factory=standard_method_evidence_factory(content),
        state_root=Path(state_root),
        dispatcher=dispatcher,
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
        execute_method=execute_standard_method_program,
        executor_digest=METHOD_PROGRAM_EXECUTOR_DIGEST,
        compiler=compiler,
        result_adapter=result_adapter,
    )


__all__ = ["compose_reproduction_method_workload"]
