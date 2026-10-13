"""Unit-native environment semantics shared by every environment family."""
from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.foundation.kernel.kernel import JsonValue
from noetrium_platform.foundation.kernel.structure import NoetriumUnit, structure_unit


ENVIRONMENT_TRAIT = "environment"
ENVIRONMENT_CAPABILITY_TRAIT = "environment.capability"


def environment_unit(
    environment_id: str,
    *,
    category: str,
    revision: str,
    capabilities: tuple[str, ...],
    parameters: Mapping[str, JsonValue] | None = None,
) -> NoetriumUnit:
    if not environment_id.strip() or not category.strip() or not revision.strip():
        raise ValueError(
            "environment identity/category/revision must be non-empty"
        )
    if not capabilities or any(
        type(capability) is not str or not capability.strip()
        for capability in capabilities
    ):
        raise ValueError("environment requires typed capabilities")
    members = tuple(
        structure_unit(
            f"{environment_id}::capability::{capability}",
            traits=(ENVIRONMENT_CAPABILITY_TRAIT,),
            parameters={"capability_id": capability},
        )
        for capability in sorted(set(capabilities))
    )
    values = {"category": category, "revision": revision}
    values.update(dict(parameters or {}))
    return structure_unit(
        environment_id,
        traits=(ENVIRONMENT_TRAIT,),
        parameters=values,
        members=members,
    )


def require_environment_unit(environment: NoetriumUnit) -> NoetriumUnit:
    if (
        type(environment) is not NoetriumUnit
        or not environment.has_trait(ENVIRONMENT_TRAIT)
    ):
        raise TypeError("environment semantics must be NoetriumUnit")
    return environment


def environment_capabilities(environment: NoetriumUnit) -> tuple[str, ...]:
    environment = require_environment_unit(environment)
    return tuple(
        str(child.parameters["capability_id"])
        for child in environment.members
        if child.has_trait(ENVIRONMENT_CAPABILITY_TRAIT)
    )


__all__ = [
    "ENVIRONMENT_CAPABILITY_TRAIT",
    "ENVIRONMENT_TRAIT",
    "environment_capabilities",
    "environment_unit",
    "require_environment_unit",
]
