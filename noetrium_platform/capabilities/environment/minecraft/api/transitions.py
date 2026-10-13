"""One Minecraft interaction as four disjoint truth projections of NoetriumUnit.

This is an evidence/journal representation, NOT an oracle for hidden Minecraft
state and NOT a replacement for the runtime authorization or physical provider.
The causal-state quotient is a semantic ideal, not a computable concrete claim.
"""
from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_digest
from noetrium_platform.foundation.kernel.unit import NoetriumUnit, role

from .contracts import MINECRAFT_ACTION_SPEC_BY_TYPE, minecraft_child_effect_rows
from .invocations import (
    require_minecraft_action_authorization,
    require_minecraft_action_invocation,
)


MINECRAFT_TRANSITION_SCHEMA = "environment.minecraft.world-transition"
MINECRAFT_OBSERVED_WORLD_SCHEMA = "environment.minecraft.observed-world"
MINECRAFT_CHILD_EFFECT_EVIDENCE_SCHEMA = "environment.minecraft.child-effect-evidence"


def minecraft_observed_world_unit(
    *,
    observation_id: str,
    generation: str,
    state_digest: str,
    decision_view: Mapping[str, JsonValue],
    base_observation_id: str | None = None,
    base_decision_view: Mapping[str, JsonValue] | None = None,
) -> NoetriumUnit:
    """One Unit semantics for first snapshots and incremental observations.

    Only an already visibility-cut decision view is accepted. New observations
    carry their own identity and complete-state digest; when a preceding
    observation exists in the same generation, the durable Unit stores its
    changed fields rather than duplicating the entire observed world.
    Nothing in this method is a claim about unobserved server state.
    """
    if not observation_id or not generation or not state_digest:
        raise ValueError("observed world must bind observation and generation")
    if (base_observation_id is None) != (base_decision_view is None):
        raise ValueError("world delta requires an identified base observation")
    projection = dict(decision_view)
    if projection.get("kind") != "minecraft_decision_view.v1":
        raise ValueError("observed world requires the canonical decision view")
    current = projection.get("state")
    if not isinstance(current, Mapping):
        raise ValueError("observed world state must be a mapping")
    encoded: Mapping[str, JsonValue]
    if base_decision_view is None:
        representation = "snapshot"
        encoded = projection
    else:
        baseline = base_decision_view.get("state")
        if base_decision_view.get("kind") != projection["kind"] or not isinstance(baseline, Mapping):
            raise ValueError("observed world delta baseline has invalid schema")
        representation = "delta"
        encoded = {
            "kind": "minecraft_decision_view.delta.v1",
            "base_observation_id": base_observation_id,
            "changed": {
                key: value
                for key, value in current.items()
                if key not in baseline or baseline[key] != value
            },
            "removed": sorted(set(baseline) - set(current)),
        }
    return NoetriumUnit(
        unit_id="minecraft.world-observation." + canonical_digest(
            {"observation_id": observation_id, "generation": generation}
        ),
        schemas=(MINECRAFT_OBSERVED_WORLD_SCHEMA,),
        attributes={
            "truth_class": "observed",
            "source": "environment_session",
            "observation_id": observation_id,
            "generation": generation,
            "base_observation_id": base_observation_id,
            "representation": representation,
            "observed_state_digest": state_digest,
            "visible_projection_digest": canonical_digest(projection),
            "visible_projection": dict(encoded),
        },
    )


def _minecraft_child_effect_units(
    *,
    invocation: NoetriumUnit,
    authorization: NoetriumUnit,
    child_effects: tuple[Mapping[str, JsonValue], ...],
) -> tuple[NoetriumUnit, ...]:
    """Lift provider-WAL child evidence into typed Units without re-authorizing it."""
    if type(child_effects) is not tuple:
        raise TypeError("Minecraft child effect evidence must be a tuple")
    normalized = minecraft_child_effect_rows(
        {"child_effects": child_effects},
        expected_action_id=str(invocation.attributes["action_id"]),
        expected_request_digest=str(invocation.attributes["request_digest"]),
        expected_invocation_unit_digest=invocation.unit_digest,
        expected_authorization_unit_digest=authorization.unit_digest,
    )
    allowed = frozenset(
        str(name) for name in authorization.attributes.get("authorized_child_actions", ())
    )
    units: list[NoetriumUnit] = []
    for row in normalized:
        if not isinstance(row, Mapping):
            raise TypeError("Minecraft child effect evidence row must be a mapping")
        action_type = str(row.get("action_type") or "")
        if action_type not in allowed:
            raise ValueError("Minecraft child effect is outside the authorized Unit closure")
        specification = MINECRAFT_ACTION_SPEC_BY_TYPE[action_type]
        request_digest = row.get("request_digest")
        if not isinstance(request_digest, str) or len(request_digest) != 64:
            raise ValueError("Minecraft child effect request digest is invalid")
        units.append(
            NoetriumUnit(
                unit_id="minecraft.child-effect." + request_digest,
                schemas=(MINECRAFT_CHILD_EFFECT_EVIDENCE_SCHEMA,),
                attributes={"truth_class": "evidenced", **dict(row)},
                roles=(
                    role("root_invocation", invocation),
                    role("authorization", authorization),
                    role("action_specification", specification),
                ),
            )
        )
    return tuple(units)


def minecraft_transition_unit(
    *,
    invocation: NoetriumUnit,
    authorization: NoetriumUnit,
    provider_instance_id: str,
    before_observation_id: str | None,
    after_observation_id: str | None,
    state_digest: str | None,
    outcome_status: str,
    effect_disposition: str,
    action_result_digest: str | None,
    effect_receipt_id: str | None,
    bridge_acknowledged: bool,
    failure_code: str | None = None,
    provider_outcome: Mapping[str, JsonValue] | None = None,
    execution_control: Mapping[str, JsonValue] | None = None,
    child_effects: tuple[Mapping[str, JsonValue], ...] = (),
) -> NoetriumUnit:
    """Encode one interaction while preserving four independent truth classes.

    ``declared`` is the exact action-invocation Unit. ``authorized`` is the
    capability-authorization Unit for that same invocation. Neither role is
    reconstructed from provider diagnostics. Observed state and physical effect
    evidence remain separate Units, so an ACK, authorization, or observation can
    never be promoted into proof that the requested world effect occurred.
    """
    invocation = require_minecraft_action_invocation(invocation)
    authorization = require_minecraft_action_authorization(
        authorization, invocation=invocation
    )
    request_digest = str(invocation.attributes["request_digest"])
    action_id = str(invocation.attributes["action_id"])
    if not provider_instance_id:
        raise ValueError("Minecraft transition provider identity must be non-empty")
    stem = "minecraft.transition." + request_digest
    child_effect_units = _minecraft_child_effect_units(
        invocation=invocation,
        authorization=authorization,
        child_effects=child_effects,
    )
    observed = NoetriumUnit(
        unit_id=stem + ".observed",
        schemas=("environment.minecraft.truth.observed",),
        attributes={
            "truth_class": "observed",
            "before_observation_id": before_observation_id,
            "after_observation_id": after_observation_id,
            "state_digest": state_digest,
        },
    )
    evidenced = NoetriumUnit(
        unit_id=stem + ".evidenced",
        schemas=("environment.minecraft.truth.evidenced",),
        attributes={
            "truth_class": "evidenced",
            "action_result_digest": action_result_digest,
            "effect_receipt_id": effect_receipt_id,
            "provider_instance_id": provider_instance_id,
            "outcome_status": outcome_status,
            "effect_disposition": effect_disposition,
            "bridge_acknowledged": bridge_acknowledged,
            "failure_code": failure_code,
            "child_effect_count": len(child_effect_units),
            "provider_outcome": dict(provider_outcome) if provider_outcome is not None else None,
            "execution_control": dict(execution_control) if execution_control is not None else None,
        },
        roles=(
            (role("child_effect", *child_effect_units),)
            if child_effect_units else ()
        ),
    )
    return NoetriumUnit(
        unit_id=stem,
        schemas=(MINECRAFT_TRANSITION_SCHEMA,),
        attributes={
            "interaction": "minecraft",
            "version": 3,
            "action_id": action_id,
            "request_digest": request_digest,
        },
        roles=(
            role("declared", invocation),
            role("authorized", authorization),
            role("observed", observed),
            role("evidenced", evidenced),
        ),
    )


__all__ = [
    "MINECRAFT_TRANSITION_SCHEMA",
    "MINECRAFT_OBSERVED_WORLD_SCHEMA",
    "MINECRAFT_CHILD_EFFECT_EVIDENCE_SCHEMA",
    "minecraft_transition_unit",
    "minecraft_observed_world_unit",
]
