from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.capabilities.participant.core.api import BoundParticipant, BoundParticipants
from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentity
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec

from ..api.contracts import (
    RunCheckpointBundle,
    RunCheckpointManifest,
    RunParticipantPayload,
)


class RunCheckpointIdentityMismatch(RuntimeError):
    """A checkpoint bundle is not valid for the requested execution identity."""


def _require_run_identity(
    manifest: RunCheckpointManifest,
    spec: ExperimentSpec,
    cycle_identity: DecisionCycleIdentity,
) -> None:
    expected = (
        spec.identity_digest(),
        cycle_identity.run_id,
        cycle_identity.session_id,
        cycle_identity.decision_cycle_id,
        cycle_identity.digest(),
    )
    actual = (
        manifest.experiment_spec_digest,
        manifest.run_id,
        manifest.session_id,
        manifest.decision_cycle_id,
        manifest.cycle_identity_digest,
    )
    if actual != expected:
        raise RunCheckpointIdentityMismatch(
            "checkpoint treatment/runtime identity mismatch: "
            f"expected={expected!r} actual={actual!r}"
        )


def _bound_topology(
    bound: BoundParticipants,
) -> tuple[dict[str, tuple[str, str]], dict[str, BoundParticipant]]:
    identities: dict[str, tuple[str, str]] = {}
    participants: dict[str, BoundParticipant] = {}
    for row in bound.participants:
        if row.role in identities:
            raise RunCheckpointIdentityMismatch(
                "bound participant topology contains duplicate roles"
            )
        identities[row.role] = (
            row.runtime.binding.digest(),
            canonical_digest(row.component),
        )
        participants[row.role] = row
    return identities, participants


def _manifest_topology(
    manifest: RunCheckpointManifest,
) -> dict[str, tuple[str, str]]:
    return {
        row.role: (
            row.checkpoint.runtime_binding_digest,
            row.checkpoint.component_digest,
        )
        for row in manifest.participant_snapshots
    }


def _payload_index(
    bundle: RunCheckpointBundle,
    expected_roles: set[str],
) -> dict[str, RunParticipantPayload]:
    payloads: dict[str, RunParticipantPayload] = {}
    for row in bundle.participant_payloads:
        role = row.ref.role
        if role in payloads:
            raise RunCheckpointIdentityMismatch(
                "checkpoint participant payload topology contains duplicate roles"
            )
        payloads[role] = row
    if set(payloads) != expected_roles:
        raise RunCheckpointIdentityMismatch(
            "checkpoint participant payload set does not match manifest"
        )
    return payloads


def _verify_payload(
    role: str,
    item: RunParticipantPayload,
    participant: BoundParticipant,
    cycle_identity: DecisionCycleIdentity,
) -> None:
    try:
        item.checkpoint.verify(
            binding=participant.runtime.binding,
            component=participant.component,
            session_id=cycle_identity.session_id,
        )
    except RuntimeError as exc:
        raise RunCheckpointIdentityMismatch(str(exc)) from exc


def _require_participant_topology(
    bundle: RunCheckpointBundle,
    bound: BoundParticipants,
    cycle_identity: DecisionCycleIdentity,
) -> None:
    expected, bound_by_role = _bound_topology(bound)
    actual = _manifest_topology(bundle.manifest)
    if actual != expected:
        raise RunCheckpointIdentityMismatch(
            "checkpoint participant topology mismatch: "
            f"expected={expected!r} actual={actual!r}"
        )
    payloads = _payload_index(bundle, set(actual))
    for role, item in payloads.items():
        _verify_payload(role, item, bound_by_role[role], cycle_identity)


def validate_restore_bundle(
    bundle: RunCheckpointBundle,
    *,
    spec: ExperimentSpec,
    bound: BoundParticipants,
    cycle_identity: DecisionCycleIdentity,
) -> RunCheckpointBundle:
    """Validate the complete restore bundle before any participant mutation."""

    _require_run_identity(bundle.manifest, spec, cycle_identity)
    _require_participant_topology(bundle, bound, cycle_identity)
    return bundle


__all__ = ["RunCheckpointIdentityMismatch", "validate_restore_bundle"]
