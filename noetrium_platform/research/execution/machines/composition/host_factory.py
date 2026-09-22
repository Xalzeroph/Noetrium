from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import (
    JsonValue,
    MachineJournalPort,
    MachineSnapshotStorePort,
)
from noetrium_platform.research.execution.machines.api.host_runtime import (
    ResearchProgramHostFactoryPort,
    ResearchProgramHostPort,
)
from noetrium_platform.research.execution.machines.program import (
    ProgramHandlerRegistry,
    ResearchProgram,
)
from noetrium_platform.research.execution.machines.program_host import (
    ResearchHostBindingRestorer,
    ResearchHostOperation,
    ResearchProgramHost,
)


class DefaultResearchProgramHostFactory(ResearchProgramHostFactoryPort):
    """Default MachineExecutor-backed implementation of the Research Program host port."""

    def build(
        self,
        *,
        host_id: str,
        program: ResearchProgram,
        operations: tuple[ResearchHostOperation, ...] = (),
        journal: MachineJournalPort,
        base_handlers: ProgramHandlerRegistry | None = None,
        snapshot_store: MachineSnapshotStorePort | None = None,
        max_steps: int = 10_000,
        dependency_identity: JsonValue = None,
        binding_restorer: ResearchHostBindingRestorer | None = None,
    ) -> ResearchProgramHostPort:
        return ResearchProgramHost(
            host_id=host_id,
            program=program,
            operations=operations,
            journal=journal,
            base_handlers=base_handlers,
            snapshot_store=snapshot_store,
            max_steps=max_steps,
            dependency_identity=dependency_identity,
            binding_restorer=binding_restorer,
        )


__all__ = ["DefaultResearchProgramHostFactory"]
