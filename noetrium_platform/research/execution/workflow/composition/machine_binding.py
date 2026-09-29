"""Bind Method authoring IR to the single generic ResearchProgram Machine host."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel import (
    DirectoryMachineJournal,
    DirectoryMachineSnapshotStore,
    canonical_digest,
)
from noetrium_platform.research.execution.machines import ResearchProgramHost

from ..api import MethodProgram, MethodRuntimeContext
from ..api.runtime_services import MethodRuntimeBinderPort
from .program_lowering import (
    lower_method_program,
    method_program_lowering_digest,
    method_program_operations,
)


def _bind_machine_method_runtime(
    program: MethodProgram,
    runtime: MethodRuntimeContext,
    *,
    state_root: str | Path,
    machine_id: str | None = None,
) -> MethodRuntimeContext:
    """Bind Method semantics to the one ResearchProgramHost/Machine Journal path."""
    if runtime.program_host is not None or runtime.machine_id is not None:
        raise ValueError("method runtime already has a generic Machine host")
    root = Path(state_root)
    root.mkdir(parents=True, exist_ok=True)
    lowered = lower_method_program(program)
    journal = DirectoryMachineJournal(root / "journal")
    snapshots = DirectoryMachineSnapshotStore(root / "snapshots")
    resolved_machine_id = machine_id or f"method:{runtime.execution.run_id}"
    budget_max_steps = runtime.execution.trial_budget.get("max_steps")
    if budget_max_steps is not None and (
        type(budget_max_steps) is not int or budget_max_steps < 1
    ):
        raise ValueError("Method TrialBudget max_steps must be positive integer")
    host = ResearchProgramHost(
        host_id="method:" + program.program_identity.implementation.method_id,
        program=lowered,
        operations=method_program_operations(program),
        journal=journal,
        snapshot_store=snapshots,
        max_steps=(10_000 if budget_max_steps is None else budget_max_steps),
        dependency_identity={
            "schema": "noetrium.method-generic-machine-binding.v1",
            "method_program_digest": program.program_digest,
            "lowering_digest": method_program_lowering_digest(program),
            "binding_plan_digest": runtime.binding_plan_digest,
            "runtime_binding_digest": runtime.effective_runtime_binding_digest,
            "schema_digest": runtime.schema_digest,
        },
    )
    return replace(
        runtime,
        program_host=host,
        machine_id=resolved_machine_id,
    )


class MachineMethodRuntimeBinder(MethodRuntimeBinderPort):
    """Bind MethodProgram to the universal ResearchProgram execution kernel."""

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "adapter": "method-research-program-runtime-binder",
            "version": 1,
        })

    def bind(
        self,
        program: MethodProgram,
        runtime: MethodRuntimeContext,
        *,
        state_root: str | Path,
        machine_id: str | None = None,
    ) -> MethodRuntimeContext:
        return _bind_machine_method_runtime(
            program,
            runtime,
            state_root=state_root,
            machine_id=machine_id,
        )


__all__ = ["MachineMethodRuntimeBinder"]
