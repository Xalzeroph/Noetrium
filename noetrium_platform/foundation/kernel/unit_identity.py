"""Identity projections for the universal NoetriumUnit carrier."""
from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from .unit import NoetriumUnit


class UnitIdentityFacet(StrEnum):
    SEMANTIC = "semantic"
    OPERATIONAL = "operational"
    REALIZATION = "realization"


class UnitIdentityProjection(Protocol):
    facet: UnitIdentityFacet
    projection_id: str

    def project(self, unit: NoetriumUnit) -> object: ...


def unit_identity(
    unit: NoetriumUnit,
    projection: UnitIdentityProjection | None = None,
) -> str:
    if type(unit) is not NoetriumUnit:
        raise TypeError("unit identity requires NoetriumUnit")
    if projection is None:
        return unit.semantic_digest
    if (
        not isinstance(projection.facet, UnitIdentityFacet)
        or not projection.projection_id.strip()
    ):
        raise ValueError(
            "unit identity projection must declare a typed facet and identity"
        )
    return canonical_digest(
        {
            "facet": projection.facet.value,
            "projection_id": projection.projection_id,
            "value": projection.project(unit),
        }
    )


def unit_semantically_equivalent(
    left: NoetriumUnit,
    right: NoetriumUnit,
) -> bool:
    return left.semantic_digest == right.semantic_digest


__all__ = [
    "UnitIdentityFacet",
    "UnitIdentityProjection",
    "unit_identity",
    "unit_semantically_equivalent",
]
