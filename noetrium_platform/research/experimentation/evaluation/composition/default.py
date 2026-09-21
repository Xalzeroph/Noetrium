from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import MachineJournalPort, MachineSnapshotStorePort
from noetrium_platform.research.execution.machines import ResearchProgramHost

from ..runtime import paired_evaluation_host


def bind_paired_evaluation_host(
    *,
    journal: MachineJournalPort,
    snapshot_store: MachineSnapshotStorePort | None = None,
) -> ResearchProgramHost:
    """Bind the canonical paired EvaluationMachine to platform Machine authority."""

    return paired_evaluation_host(
        journal=journal,
        snapshot_store=snapshot_store,
    )


__all__ = ["bind_paired_evaluation_host"]
