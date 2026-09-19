"""High-level binding of MethodProgram execution to the durable Machine kernel."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel import (
    DirectoryMachineJournal,
    DirectoryMachineSnapshotStore,
    InMemoryMachineJournal,
    InMemoryMachineSnapshotStore,
    MachineIdentity,
    MachineKind,
    MachineProgramRef,
    MachineExecutor,
    ProgramLock,
    canonical_digest,
)
from ..api import MethodProgram, MethodRuntimeContext
from ..runtime import MachineMethodTransitionAuthority

def _program_ref(program: MethodProgram, runtime: MethodRuntimeContext) -> MachineProgramRef:
    dependency_digest = runtime.effective_runtime_binding_digest or canonical_digest({
        "required_capabilities": program.required_capabilities,
        "program_identity": program.program_identity.digest(),
    })
    schema_digest = runtime.schema_digest or canonical_digest({
        "state": program.state_schema,
        "input": program.input_schema,
        "output": program.output_schema,
    })
    data_digest = runtime.binding_plan_digest or canonical_digest({"binding_plan": None})
    return MachineProgramRef(
        program_digest=program.program_digest,
        schema_id="noetrium.method-machine.v2",
        program_kind="method",
        program_version="2",
        program_lock=ProgramLock(
            code_digest=program.program_digest,
            dependency_digest=dependency_digest,
            schema_digest=schema_digest,
            interpreter_digest=canonical_digest({"interpreter": "umm-node-machine", "version": 2}),
            data_digest=data_digest,
            config_digest=canonical_digest(program.configuration),
        ),
    )

def bind_machine_method_runtime(
    program: MethodProgram,
    runtime: MethodRuntimeContext,
    *,
    state_root: str | Path | None = None,
    machine_id: str | None = None,
) -> MethodRuntimeContext:
    """Return a MethodRuntimeContext whose execution truth is Machine-backed.

    With ``state_root=None`` the authority is process-local. Supplying a root
    enables crash-durable Journal + verified Machine snapshots without changing
    downstream MethodProgram code.
    """
    if runtime.transitions is not None:
        raise ValueError("method runtime already has a transition authority")
    identity = MachineIdentity(
        machine_id or f"method:{runtime.execution.run_id}",
        MachineKind.METHOD,
        "2",
        f"program:{program.program_digest[:16]}",
    )
    if state_root is None:
        journal = InMemoryMachineJournal()
        snapshots = InMemoryMachineSnapshotStore()
    else:
        root = Path(state_root)
        root.mkdir(parents=True, exist_ok=True)
        journal = DirectoryMachineJournal(root / "journal")
        snapshots = DirectoryMachineSnapshotStore(root / "snapshots")
    machine = MachineExecutor(
        identity=identity,
        program=_program_ref(program, runtime),
        journal=journal,
        snapshot_store=snapshots,
    )
    return replace(runtime, transitions=MachineMethodTransitionAuthority(machine))


__all__ = ["bind_machine_method_runtime"]
