from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import ComponentIdentity, canonical_digest

from ..api.contracts import RunCheckpointManifest, RunParticipantPayload
from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentity
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec


CHECKPOINT_STORE_IDENTITY = ComponentIdentity(
    "platform.run_checkpoint_store",
    "run_checkpoint_store",
    "4",
    "4",
    "checkpoint-store-v4",
)


def build_checkpoint_manifest(
    *,
    spec: ExperimentSpec,
    participant_payloads: tuple[RunParticipantPayload, ...],
    cycle_identity: DecisionCycleIdentity,
) -> RunCheckpointManifest:
    participant_refs = tuple(item.ref for item in participant_payloads)
    identity = {
        "experiment_spec_digest": spec.identity_digest(),
        "cycle_identity_digest": cycle_identity.digest(),
        "participant_snapshots": participant_refs,
    }
    checkpoint_id = f"checkpoint:{canonical_digest(identity)}"
    return RunCheckpointManifest(
        checkpoint_id=checkpoint_id,
        schema_version="4",
        experiment_spec_digest=spec.identity_digest(),
        run_id=cycle_identity.run_id,
        session_id=cycle_identity.session_id,
        decision_cycle_id=cycle_identity.decision_cycle_id,
        cycle_identity_digest=cycle_identity.digest(),
        participant_snapshots=participant_refs,
    )


__all__ = ["CHECKPOINT_STORE_IDENTITY", "build_checkpoint_manifest"]
