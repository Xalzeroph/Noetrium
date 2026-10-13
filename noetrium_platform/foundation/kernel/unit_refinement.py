"""Refinement law over the sole NoetriumUnit carrier."""
from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from .structure import (
    boundary_input,
    boundary_output,
    port_mode,
    port_type,
    type_assignable_to,
)
from .unit import NoetriumUnit


def boundary_refines(candidate: NoetriumUnit, required: NoetriumUnit) -> bool:
    ci = {row.unit_id: row for row in candidate.units("input")}
    ri = {row.unit_id: row for row in required.units("input")}
    co = {row.unit_id: row for row in candidate.units("output")}
    ro = {row.unit_id: row for row in required.units("output")}
    for name, req in ri.items():
        got = ci.get(name)
        if (
            got is None
            or port_mode(got) != port_mode(req)
            or not type_assignable_to(port_type(req), port_type(got))
        ):
            return False
    for name, req in ro.items():
        got = co.get(name)
        if (
            got is None
            or port_mode(got) != port_mode(req)
            or not type_assignable_to(port_type(got), port_type(req))
        ):
            return False
    return (
        candidate.units("state") == required.units("state")
        and candidate.units("effect") == required.units("effect")
        and candidate.units("scope") == required.units("scope")
        and candidate.units("evidence") == required.units("evidence")
    )


@dataclass(frozen=True, slots=True)
class UnitRefinementWitness:
    relation_id: str
    source_semantic_digest: str
    target_semantic_digest: str
    proof_digest: str

    @classmethod
    def boundary(
        cls, source: NoetriumUnit, target: NoetriumUnit
    ) -> "UnitRefinementWitness":
        if not boundary_refines(target.boundary, source.boundary):
            raise ValueError("target unit does not refine source boundary")
        relation_id = "foundation.boundary-refinement"
        return cls(
            relation_id,
            source.semantic_digest,
            target.semantic_digest,
            canonical_digest(
                (relation_id, source.semantic_digest, target.semantic_digest)
            ),
        )


def unit_equivalent(left: NoetriumUnit, right: NoetriumUnit) -> bool:
    return left.semantic_digest == right.semantic_digest


__all__ = ["UnitRefinementWitness", "boundary_refines", "unit_equivalent"]
