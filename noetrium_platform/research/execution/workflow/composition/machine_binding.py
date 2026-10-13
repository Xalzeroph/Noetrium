"""Bind Method authoring IR to the single generic NoetriumUnit Machine host."""
from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel.unit_host import BoundExecutableUnit

from noetrium_platform.capabilities.api import participant_implementation_id

from dataclasses import replace
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel import (
    DirectoryMachineJournal,
    DirectoryMachineSnapshotStore,
    canonical_digest,
)


from ..api import (NoetriumUnit, MethodRuntimeContext, method_program_digest, method_program_identity)
from ..runtime.program_lowering import method_program_operations


def bind_machine_method_runtime(
    program: NoetriumUnit,
    runtime: MethodRuntimeContext,
    *,
    state_root: str | Path,
    machine_id: str | None = None,
) -> MethodRuntimeContext:
    """Bind Method semantics to the one BoundExecutableUnit/Machine Journal path."""
    if runtime.program_binding is not None or runtime.machine_id is not None:
        raise ValueError("method runtime already has a generic Machine host")
    root = Path(state_root)
    root.mkdir(parents=True, exist_ok=True)
    journal = DirectoryMachineJournal(root / "journal")
    snapshots = DirectoryMachineSnapshotStore(root / "snapshots")
    resolved_machine_id = machine_id or f"method:{runtime.execution.run_id}"
    host = BoundExecutableUnit(
        host_id="method:" + participant_implementation_id(method_program_identity(program)),
        unit=program,
        operations=method_program_operations(program),
        journal=journal,
        snapshot_store=snapshots,
        max_steps=None,
        dependency_identity={
            "schema": "noetrium.method-unit-machine-binding.v2",
            "method_program_digest": method_program_digest(program),
            "binding_plan_digest": runtime.binding_plan_digest,
            "runtime_binding_digest": runtime.effective_runtime_binding_digest,
            "schema_digest": runtime.schema_digest,
        },
    )
    return replace(
        runtime,
        program_binding=host,
        machine_id=resolved_machine_id,
    )


METHOD_RUNTIME_BINDER_DIGEST = canonical_digest({
    "adapter": "method-unit-runtime-binder",
    "version": 3,
})



__all__ = ["METHOD_RUNTIME_BINDER_DIGEST", "bind_machine_method_runtime"]
