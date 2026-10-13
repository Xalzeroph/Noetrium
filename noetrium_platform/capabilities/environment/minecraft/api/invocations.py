"""First-class Unit semantics for concrete Minecraft action invocations.

Action specifications describe *what may be called*.  These Units bind one exact
runtime request to that specification and to the capability authorization cut
that admitted (or rejected) it.  They do not claim a physical effect and they do
not impersonate Resource Authority leases or Effect Journal receipts.
"""
from __future__ import annotations

from collections.abc import Mapping
from functools import cache

from noetrium_platform.capabilities.environment.api.contracts import (
    ActionRequest,
    action_request_digest,
)
from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_digest
from noetrium_platform.foundation.kernel.unit import NoetriumUnit, role

from .contracts import (
    MINECRAFT_ACTION_SPEC_BY_TYPE,
    MINECRAFT_ACTION_TYPES,
    minecraft_action_optional_actions,
    minecraft_action_required_actions,
    minecraft_action_required_closure,
    minecraft_action_unavailable_dependencies,
)


MINECRAFT_ACTION_INVOCATION_SCHEMA = "environment.minecraft.action-invocation"
MINECRAFT_ACTION_AUTHORIZATION_SCHEMA = "environment.minecraft.action-authorization"


def _request_context(request: ActionRequest) -> dict[str, JsonValue]:
    context = request.context
    # Keep the same scientific identity fields as action_request_digest().
    # Trace/span telemetry is intentionally excluded from semantic identity.
    return {
        "run_id": context.run_id,
        "study_id": context.study_id,
        "lifetime_id": context.lifetime_id,
        "task_id": context.task_id,
        "decision_cycle_id": context.decision_cycle_id,
        "checkpoint_id": context.checkpoint_id,
        "source_generation": context.generation("environment"),
    }


def require_minecraft_action_invocation(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_schema(
        MINECRAFT_ACTION_INVOCATION_SCHEMA
    ):
        raise TypeError("Minecraft action invocation must be a typed NoetriumUnit")
    action_type = value.attributes.get("action_type")
    request_digest = value.attributes.get("request_digest")
    if action_type not in MINECRAFT_ACTION_SPEC_BY_TYPE:
        raise ValueError("Minecraft action invocation references unknown action semantics")
    if not isinstance(request_digest, str) or len(request_digest) != 64:
        raise ValueError("Minecraft action invocation request digest is invalid")
    specification = value.one_unit("specification")
    if specification.unit_digest != MINECRAFT_ACTION_SPEC_BY_TYPE[action_type].unit_digest:
        raise ValueError("Minecraft action invocation specification identity drifted")
    return value


def minecraft_action_invocation_unit(request: ActionRequest) -> NoetriumUnit:
    """Bind one exact ActionRequest to the authoritative action-specification Unit."""
    if not isinstance(request, ActionRequest):
        raise TypeError("Minecraft action invocation requires ActionRequest")
    try:
        specification = MINECRAFT_ACTION_SPEC_BY_TYPE[request.action_type]
    except KeyError as exc:
        raise ValueError("Minecraft action invocation references unsupported action") from exc
    digest = action_request_digest(request)
    return NoetriumUnit(
        unit_id="minecraft.action-invocation." + digest,
        schemas=(MINECRAFT_ACTION_INVOCATION_SCHEMA,),
        attributes={
            "truth_class": "declared",
            "action_id": request.action_id,
            "action_type": request.action_type,
            "request_digest": digest,
            "arguments": request.payload,
            "scientific_context": _request_context(request),
        },
        roles=(role("specification", specification),),
    )


@cache
def minecraft_action_authorized_child_types(
    action_type: str,
    allowed_action_types: frozenset[str],
) -> tuple[str, ...]:
    """Return the exact transitive child capability cut a composite may invoke.

    Required descendants are admitted only when the root closure is complete.
    Optional children are admitted only when the optional child and all of its
    own required descendants are present in the same authorization cut.
    """
    if action_type not in MINECRAFT_ACTION_SPEC_BY_TYPE:
        raise ValueError("Minecraft authorization references unknown action")
    if (
        type(allowed_action_types) is not frozenset
        or not allowed_action_types.issubset(MINECRAFT_ACTION_TYPES)
    ):
        raise ValueError("Minecraft authorization action subset is invalid")
    if action_type not in allowed_action_types:
        return ()
    if minecraft_action_unavailable_dependencies(action_type, allowed_action_types):
        return ()

    result = set(minecraft_action_required_closure(action_type))
    scan = [action_type, *sorted(result)]
    seen: set[str] = set()
    while scan:
        current = scan.pop()
        if current in seen:
            continue
        seen.add(current)
        for optional in minecraft_action_optional_actions(
            MINECRAFT_ACTION_SPEC_BY_TYPE[current]
        ):
            optional_closure = minecraft_action_required_closure(optional)
            if optional in allowed_action_types and optional_closure.issubset(
                allowed_action_types
            ):
                newly_admitted = {optional, *optional_closure}
                result.update(newly_admitted)
                scan.extend(sorted(newly_admitted))
    result.discard(action_type)
    return tuple(sorted(result))


@cache
def minecraft_action_authorized_child_depth(
    action_type: str,
    allowed_action_types: frozenset[str],
) -> int:
    """Exact maximum nesting depth of the admitted Unit child-capability DAG."""
    children = frozenset(
        minecraft_action_authorized_child_types(action_type, allowed_action_types)
    )
    if not children:
        return 0
    visiting: set[str] = set()
    memo: dict[str, int] = {}

    def depth(current: str) -> int:
        cached = memo.get(current)
        if cached is not None:
            return cached
        if current in visiting:
            raise ValueError("Minecraft authorized child capability graph is cyclic")
        visiting.add(current)
        specification = MINECRAFT_ACTION_SPEC_BY_TYPE[current]
        edges = tuple(
            child for child in (
                *minecraft_action_required_actions(specification),
                *minecraft_action_optional_actions(specification),
            )
            if child in children
        )
        value = 0 if not edges else 1 + max(depth(child) for child in edges)
        visiting.remove(current)
        memo[current] = value
        return value

    return depth(action_type)


@cache
def _catalog_attestation_digest(allowed_action_types: frozenset[str]) -> str:
    return canonical_digest(tuple(
        (name, MINECRAFT_ACTION_SPEC_BY_TYPE[name].unit_digest)
        for name in sorted(allowed_action_types)
    ))


def require_minecraft_action_authorization(
    value: NoetriumUnit,
    *,
    invocation: NoetriumUnit | None = None,
) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_schema(
        MINECRAFT_ACTION_AUTHORIZATION_SCHEMA
    ):
        raise TypeError("Minecraft action authorization must be a typed NoetriumUnit")
    bound = value.one_unit("invocation")
    require_minecraft_action_invocation(bound)
    if invocation is not None and bound.unit_digest != require_minecraft_action_invocation(
        invocation
    ).unit_digest:
        raise ValueError("Minecraft action authorization binds another invocation")
    return value


def minecraft_action_authorization_unit(
    invocation: NoetriumUnit,
    *,
    allowed_action_types: frozenset[str],
    contract_validation: str,
    rejection_code: str | None = None,
) -> NoetriumUnit:
    """Attest the exact capability-catalog authorization cut for an invocation.

    This Unit is deliberately *not* a Resource Authority lease and not an effect
    receipt.  It records capability authorization truth only.
    """
    invocation = require_minecraft_action_invocation(invocation)
    if contract_validation not in {"not_reached", "passed", "failed"}:
        raise ValueError("Minecraft contract validation state is invalid")
    if rejection_code is not None and (
        not isinstance(rejection_code, str) or not rejection_code.strip()
    ):
        raise ValueError("Minecraft authorization rejection code must be non-empty")
    if (
        type(allowed_action_types) is not frozenset
        or not allowed_action_types.issubset(MINECRAFT_ACTION_TYPES)
    ):
        raise ValueError("Minecraft authorization action subset is invalid")

    action_type = str(invocation.attributes["action_type"])
    missing = (
        ()
        if action_type not in allowed_action_types
        else minecraft_action_unavailable_dependencies(
            action_type, allowed_action_types
        )
    )
    authorized = (
        action_type in allowed_action_types
        and not missing
        and contract_validation == "passed"
        and rejection_code is None
    )
    children = (
        minecraft_action_authorized_child_types(action_type, allowed_action_types)
        if authorized
        else ()
    )
    child_specs = tuple(MINECRAFT_ACTION_SPEC_BY_TYPE[name] for name in children)
    max_child_depth = (
        minecraft_action_authorized_child_depth(action_type, allowed_action_types)
        if authorized else 0
    )
    attributes: dict[str, JsonValue] = {
        "truth_class": "authorized",
        "authority_kind": "capability_action_catalog",
        "authorization_state": "authorized" if authorized else "rejected",
        "contract_validation": contract_validation,
        "action_type": action_type,
        "request_digest": str(invocation.attributes["request_digest"]),
        "authorized_child_actions": children,
        "max_child_depth": max_child_depth,
        "missing_required_child_actions": tuple(missing),
        "catalog_attestation_digest": _catalog_attestation_digest(allowed_action_types),
        "rejection_code": rejection_code,
        "resource_authority_receipt": None,
        "effect_journal_receipt": None,
    }
    return NoetriumUnit(
        unit_id="minecraft.action-authorization."
        + canonical_digest(
            {
                "invocation": invocation.unit_digest,
                "catalog": attributes["catalog_attestation_digest"],
                "contract_validation": contract_validation,
                "children": tuple((name, spec.unit_digest) for name, spec in zip(children, child_specs)),
                "rejection_code": rejection_code,
            }
        ),
        schemas=(MINECRAFT_ACTION_AUTHORIZATION_SCHEMA,),
        attributes=attributes,
        roles=(
            role("invocation", invocation),
            role("action_specification", MINECRAFT_ACTION_SPEC_BY_TYPE[action_type]),
            role("authorized_child_specification", *child_specs),
        ),
    )


__all__ = [
    "MINECRAFT_ACTION_AUTHORIZATION_SCHEMA",
    "MINECRAFT_ACTION_INVOCATION_SCHEMA",
    "minecraft_action_authorization_unit",
    "minecraft_action_authorized_child_depth",
    "minecraft_action_authorized_child_types",
    "minecraft_action_invocation_unit",
    "require_minecraft_action_authorization",
    "require_minecraft_action_invocation",
]
