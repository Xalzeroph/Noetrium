from __future__ import annotations

from pathlib import Path

from noetrium_platform.research.execution.api import (
    MethodEvidenceFactoryPort,
    NoetriumUnit,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.composition.machine_binding import (
    METHOD_RUNTIME_BINDER_DIGEST,
    bind_machine_method_runtime,
)
from noetrium_platform.research.execution.workflow.runtime import (
    execute_bound_method_program,
)
from .method_evidence import ArtifactBackedMethodEvidenceFactory
from .research_execution_content import ResearchExecutionContentAuthorities


from noetrium_platform.foundation.kernel.kernel import canonical_digest

METHOD_PROGRAM_EXECUTOR_DIGEST = canonical_digest({
    "executor": "noetrium.standard-method-program-executor.v2",
})


def execute_standard_method_program(
    program: NoetriumUnit,
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


def standard_method_executable_unit_digest(program: NoetriumUnit) -> str:
    """Project Method IR to the exact NoetriumUnit identity owned by its journal."""
    if not isinstance(program, NoetriumUnit):
        raise TypeError("standard Method lowering requires NoetriumUnit")
    return program.unit_digest


def standard_method_evidence_factory(
    content: ResearchExecutionContentAuthorities,
) -> MethodEvidenceFactoryPort:
    if type(content) is not ResearchExecutionContentAuthorities:
        raise TypeError(
            "standard Method evidence requires shared ResearchExecutionContentAuthorities"
        )
    return ArtifactBackedMethodEvidenceFactory(content)


def bind_standard_method_runtime(
    program: NoetriumUnit,
    runtime: MethodRuntimeContext,
    *,
    state_root: str | Path,
    machine_id: str | None = None,
) -> MethodRuntimeContext:
    return bind_machine_method_runtime(
        program,
        runtime,
        state_root=state_root,
        machine_id=machine_id,
    )


__all__ = [
    "bind_standard_method_runtime",
    "standard_method_evidence_factory",
    "standard_method_executable_unit_digest",
    "METHOD_PROGRAM_EXECUTOR_DIGEST",
    "execute_standard_method_program",
    "METHOD_RUNTIME_BINDER_DIGEST",
]
