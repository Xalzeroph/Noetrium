from __future__ import annotations

from pathlib import Path

from noetrium_platform.research.execution.api import (
    MethodEvidenceFactoryPort,
    MethodProgram,
    MethodRuntimeBinderPort,
    MethodRuntimeContext,
)
from noetrium_platform.research.execution.workflow.composition.machine_binding import (
    MachineMethodRuntimeBinder,
)
from .method_evidence import ArtifactBackedMethodEvidenceFactory
from .research_execution_content import ResearchExecutionContentAuthorities


def standard_method_runtime_binder() -> MethodRuntimeBinderPort:
    return MachineMethodRuntimeBinder()


def standard_method_evidence_factory(
    content: ResearchExecutionContentAuthorities,
) -> MethodEvidenceFactoryPort:
    if type(content) is not ResearchExecutionContentAuthorities:
        raise TypeError(
            "standard Method evidence requires shared ResearchExecutionContentAuthorities"
        )
    return ArtifactBackedMethodEvidenceFactory(content)


def bind_standard_method_runtime(
    program: MethodProgram,
    runtime: MethodRuntimeContext,
    *,
    state_root: str | Path,
    machine_id: str | None = None,
) -> MethodRuntimeContext:
    return standard_method_runtime_binder().bind(
        program,
        runtime,
        state_root=state_root,
        machine_id=machine_id,
    )


__all__ = [
    "bind_standard_method_runtime",
    "standard_method_evidence_factory",
    "standard_method_runtime_binder",
]
