from __future__ import annotations

from pathlib import Path

from noetrium_platform.composition.method_runtime import (
    bind_standard_method_runtime,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodProgram,
    MethodRunResult,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.runtime import (
    UniversalMethodMachine,
)


def execute_method_program_canonically(
    program: MethodProgram,
    *,
    runtime: MethodRuntimeContext,
    input_value: object = None,
    initial_state: object = None,
    resume: bool = False,
    state_root: str | Path | None = None,
) -> MethodRunResult:
    """Execute a MethodProgram through the canonical UMM/Machine path.

    Internal scientific-test helper only; not a public or compatibility facade.
    """

    bound_runtime = runtime
    if bound_runtime.transitions is None:
        if resume and state_root is None:
            raise ValueError(
                "durable method resume requires state_root or a pre-bound "
                "transition authority"
            )
        bound_runtime = bind_standard_method_runtime(
            program,
            runtime,
            state_root=state_root,
        )
    return UniversalMethodMachine().run(
        program,
        runtime=bound_runtime,
        input_value=input_value,
        initial_state=initial_state,
        resume=resume,
    )


__all__ = ["execute_method_program_canonically"]
