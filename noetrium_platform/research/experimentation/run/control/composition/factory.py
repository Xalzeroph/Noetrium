from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    MachineJournalPort,
    MachineSnapshotStorePort,
)
from noetrium_platform.research.experimentation.run.api.artifacts import (
    RunArtifactVerificationPort,
)
from noetrium_platform.research.experimentation.run.identity.api import RunIdentity
from noetrium_platform.research.experimentation.run.manifest.api import RunLaunchManifest
from noetrium_platform.research.experimentation.run.runtime import (
    RunMachineBinding,
    RunMachineSession,
)

from ..api import (
    RunControlCheckpointStorePort,
    RunControlEvidencePort,
    RunControlLifecyclePort,
    RunControlPort,
    RunControlReconciliationPort,
)
from ..runtime import DurableRunControl


def build_durable_run_control(
    *,
    identity: RunIdentity,
    manifest: RunLaunchManifest,
    run_machine_journal: MachineJournalPort,
    lifecycle: RunControlLifecyclePort,
    checkpoint_store: RunControlCheckpointStorePort,
    reconciliation: RunControlReconciliationPort,
    evidence: RunControlEvidencePort,
    artifact_verifier: RunArtifactVerificationPort,
    run_machine_snapshot_store: MachineSnapshotStorePort | None = None,
) -> RunControlPort:
    """Bind operator control to the same journal-backed RunMachine authority."""

    if not isinstance(run_machine_journal, MachineJournalPort):
        raise TypeError(
            "durable run control requires the shared RunMachine journal"
        )
    run_machine = RunMachineSession.open(
        binding=RunMachineBinding(
            identity=identity,
            experiment_spec_digest=manifest.experiment_spec_digest,
            run_manifest_digest=manifest.digest(),
        ),
        initial_context=ExecutionContext(
            identity.run_id,
            identity.trace_id,
            "run-control",
        ),
        journal=run_machine_journal,
        snapshot_store=run_machine_snapshot_store,
    )
    return DurableRunControl(
        identity=identity,
        manifest=manifest,
        run_machine=run_machine,
        lifecycle=lifecycle,
        checkpoint_store=checkpoint_store,
        reconciliation=reconciliation,
        evidence=evidence,
        artifact_verifier=artifact_verifier,
    )


__all__ = ["build_durable_run_control"]
