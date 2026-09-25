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
from noetrium_platform.research.execution.workflow.providers.method_evidence import (
    DirectoryMethodEvidenceFactory,
)


def standard_method_runtime_binder() -> MethodRuntimeBinderPort:
    return MachineMethodRuntimeBinder()


def standard_method_evidence_factory() -> MethodEvidenceFactoryPort:
    return DirectoryMethodEvidenceFactory()


def bind_standard_method_runtime(
    program: MethodProgram,
    runtime: MethodRuntimeContext,
    *,
    state_root: str | Path | None = None,
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
