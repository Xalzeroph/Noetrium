from __future__ import annotations

import pytest

from noetrium_platform.capabilities.environment.api import ActionRequest, action_request_digest
from noetrium_platform.capabilities.environment.minecraft.api import (
    MINECRAFT_ACTION_SPEC_BY_TYPE,
    minecraft_action_authorization_unit,
    minecraft_action_authorized_child_depth,
    minecraft_action_authorized_child_types,
    minecraft_action_invocation_unit,
    require_minecraft_action_authorization,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.foundation.kernel.unit_codec import decode_unit, encode_unit


def _request(payload=None):
    return ActionRequest(
        "root-skill",
        "excavate_region",
        {"corner_a": {"x": 0, "y": 64, "z": 0}, "corner_b": {"x": 0, "y": 64, "z": 0}} if payload is None else payload,
        ExecutionContext(
            "run", "trace-a", "span-a", study_id="study", task_id="task",
            decision_cycle_id="cycle", lifetime_id="life",
        ),
    )


def _allowed():
    return frozenset({"excavate_region", "collect_block"})


def test_invocation_unit_binds_exact_request_and_action_specification():
    request = _request()
    invocation = minecraft_action_invocation_unit(request)
    assert invocation.attributes["request_digest"] == action_request_digest(request)
    assert invocation.attributes["arguments"]["corner_a"] == {"x": 0, "y": 64, "z": 0}
    assert invocation.one_unit("specification").unit_digest == (
        MINECRAFT_ACTION_SPEC_BY_TYPE["excavate_region"].unit_digest
    )
    assert decode_unit(encode_unit(invocation)).unit_digest == invocation.unit_digest


def test_invocation_identity_ignores_trace_span_but_tracks_scientific_request():
    base = _request()
    traced = ActionRequest(
        base.action_id, base.action_type, base.payload,
        ExecutionContext(
            "run", "different-trace", "different-span", study_id="study",
            task_id="task", decision_cycle_id="cycle", lifetime_id="life",
        ),
    )
    changed = _request({"corner_a": {"x": 1, "y": 64, "z": 0}, "corner_b": {"x": 1, "y": 64, "z": 0}})
    assert minecraft_action_invocation_unit(base).unit_digest == minecraft_action_invocation_unit(traced).unit_digest
    assert minecraft_action_invocation_unit(base).unit_digest != minecraft_action_invocation_unit(changed).unit_digest


def test_authorization_unit_binds_transitive_child_capability_units():
    invocation = minecraft_action_invocation_unit(_request())
    authorization = minecraft_action_authorization_unit(
        invocation, allowed_action_types=_allowed(), contract_validation="passed"
    )
    assert authorization.attributes["authorization_state"] == "authorized"
    assert authorization.attributes["authorized_child_actions"] == ("collect_block",)
    assert authorization.attributes["max_child_depth"] == 1
    assert minecraft_action_authorized_child_depth("excavate_region", _allowed()) == 1
    child_units = authorization.units("authorized_child_specification")
    assert {unit.unit_id for unit in child_units} == set(
        authorization.attributes["authorized_child_actions"]
    )
    assert require_minecraft_action_authorization(
        authorization, invocation=invocation
    ).unit_digest == authorization.unit_digest


def test_optional_child_is_not_authorized_when_its_required_closure_is_missing():
    # craft_item may conditionally place a carried crafting table. Without
    # place_block permission, the child capability must not be projected.
    assert minecraft_action_authorized_child_types(
        "craft_item", frozenset({"craft_item"})
    ) == ()
    assert minecraft_action_authorized_child_depth(
        "craft_item", frozenset({"craft_item"})
    ) == 0
    assert minecraft_action_authorized_child_types(
        "craft_item", frozenset({"craft_item", "place_block"})
    ) == ("place_block",)
    assert minecraft_action_authorized_child_depth(
        "craft_item", frozenset({"craft_item", "place_block"})
    ) == 1
    assert minecraft_action_authorized_child_depth(
        "collect_block", frozenset({"collect_block"})
    ) == 0


def test_authorization_rejects_missing_required_composite_closure():
    invocation = minecraft_action_invocation_unit(_request())
    authorization = minecraft_action_authorization_unit(
        invocation,
        allowed_action_types=frozenset({"excavate_region"}),
        contract_validation="not_reached",
        rejection_code="ACTION_CHILD_CAPABILITY_NOT_AUTHORIZED",
    )
    assert authorization.attributes["authorization_state"] == "rejected"
    assert authorization.attributes["authorized_child_actions"] == ()
    assert authorization.attributes["missing_required_child_actions"] == ("collect_block",)


def test_authorization_cannot_be_rebound_to_another_invocation():
    first = minecraft_action_invocation_unit(_request())
    auth = minecraft_action_authorization_unit(
        first, allowed_action_types=_allowed(), contract_validation="passed"
    )
    second = minecraft_action_invocation_unit(_request({"corner_a": {"x": 1, "y": 64, "z": 0}, "corner_b": {"x": 1, "y": 64, "z": 0}}))
    with pytest.raises(ValueError, match="another invocation"):
        require_minecraft_action_authorization(auth, invocation=second)
