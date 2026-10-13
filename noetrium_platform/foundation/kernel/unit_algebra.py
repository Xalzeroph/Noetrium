"""Primitive composition and persistent rewrite algebra for NoetriumUnit."""
from __future__ import annotations

from collections.abc import Callable

from .structure import boundary_unit, endpoint_unit, relation_unit, structure_unit
from .unit import NoetriumUnit, UnitRef
from .unit_refinement import boundary_refines

COMPOSITION_RELATION = "foundation.compose"


def unit_parallel(unit_id: str, *units: NoetriumUnit) -> NoetriumUnit:
    if len(units) < 1 or any(type(row) is not NoetriumUnit for row in units):
        raise TypeError("parallel requires NoetriumUnit operands")
    if len({row.unit_id for row in units}) != len(units):
        raise ValueError("parallel operands require unique unit ids")
    return structure_unit(
        unit_id,
        traits=("foundation.parallel",),
        members=tuple(units),
    )


def unit_compose(unit_id: str, *units: NoetriumUnit) -> NoetriumUnit:
    if len(units) < 2 or any(type(row) is not NoetriumUnit for row in units):
        raise TypeError("compose requires at least two NoetriumUnit operands")
    relations: list[NoetriumUnit] = []
    for left, right in zip(units, units[1:]):
        left_outputs = {row.unit_id: row for row in left.boundary.units("output")}
        right_inputs = {row.unit_id: row for row in right.boundary.units("input")}
        common = tuple(sorted(set(left_outputs) & set(right_inputs)))
        if not common:
            raise ValueError(
                f"composition has no shared boundary ports: "
                f"{left.unit_id}->{right.unit_id}"
            )
        from .structure import port_type, type_assignable_to

        for name in common:
            if not type_assignable_to(
                port_type(left_outputs[name]),
                port_type(right_inputs[name]),
            ):
                raise ValueError(f"composition port type mismatch: {name}")
            relations.append(
                relation_unit(
                    (endpoint_unit(left.unit_id, name),),
                    (endpoint_unit(right.unit_id, name),),
                    COMPOSITION_RELATION,
                )
            )
    first = units[0].boundary
    last = units[-1].boundary
    effects = tuple(
        sorted(
            set(first.units("effect") + last.units("effect")),
            key=lambda row: row.unit_id,
        )
    )
    evidence = tuple(
        sorted(
            set(first.units("evidence") + last.units("evidence")),
            key=lambda row: row.unit_id,
        )
    )
    boundary = boundary_unit(
        inputs=first.units("input"),
        outputs=last.units("output"),
        effects=effects,
        evidence=evidence,
    )
    return structure_unit(
        unit_id,
        traits=("foundation.composition",),
        boundary=boundary,
        members=tuple(units),
        relations=tuple(relations),
    )


def _rebuild_with_member(
    unit: NoetriumUnit,
    member_id: str,
    replacement: NoetriumUnit,
) -> NoetriumUnit:
    return structure_unit(
        unit.unit_id,
        traits=unit.traits,
        parameters=unit.parameters,
        boundary=unit.boundary,
        atoms=unit.atoms,
        symbols=unit.symbols,
        symbol_ids=unit.symbol_ids,
        members=tuple(
            replacement if member.unit_id == member_id else member
            for member in unit.members
        ),
        relations=unit.relations,
    )


def unit_replace_at_ref(
    unit: NoetriumUnit,
    ref: UnitRef,
    replacement: NoetriumUnit,
) -> NoetriumUnit:
    if type(unit) is not NoetriumUnit or type(replacement) is not NoetriumUnit:
        raise TypeError("unit replacement requires NoetriumUnit values")
    if type(ref) is not UnitRef:
        raise TypeError("unit replacement requires UnitRef")
    if not ref.path or ref.path[0] != unit.unit_id:
        raise ValueError("replacement ref is outside the root unit")
    if replacement.unit_id != ref.path[-1]:
        raise ValueError("replacement must preserve target unit_id")
    if len(ref.path) == 1:
        if not boundary_refines(replacement.boundary, unit.boundary):
            raise ValueError("replacement does not refine root boundary")
        return replacement

    ancestors: list[tuple[NoetriumUnit, str]] = []
    current = unit
    for member_id in ref.path[1:]:
        try:
            member = current.member(member_id)
        except LookupError as exc:
            raise LookupError(
                f"unit replacement path does not exist: {ref.path!r}"
            ) from exc
        ancestors.append((current, member_id))
        current = member

    if not boundary_refines(replacement.boundary, current.boundary):
        raise ValueError("replacement does not refine substituted boundary")

    rebuilt = replacement
    for parent, member_id in reversed(ancestors):
        rebuilt = _rebuild_with_member(parent, member_id, rebuilt)
    return rebuilt


def unit_rewrite_at_ref(
    unit: NoetriumUnit,
    ref: UnitRef,
    rewrite: Callable[[NoetriumUnit], NoetriumUnit],
) -> NoetriumUnit:
    if not callable(rewrite):
        raise TypeError("unit rewrite must be callable")
    current = unit
    if not ref.path or ref.path[0] != unit.unit_id:
        raise ValueError("rewrite ref is outside the root unit")
    for member_id in ref.path[1:]:
        current = current.member(member_id)
    replacement = rewrite(current)
    if type(replacement) is not NoetriumUnit:
        raise TypeError("unit rewrite must return NoetriumUnit")
    return unit_replace_at_ref(unit, ref, replacement)


def unit_substitute(
    unit: NoetriumUnit,
    member_id: str,
    replacement: NoetriumUnit,
) -> NoetriumUnit:
    return unit_replace_at_ref(
        unit,
        UnitRef((unit.unit_id, member_id)),
        replacement,
    )


__all__ = [
    "COMPOSITION_RELATION",
    "unit_compose",
    "unit_parallel",
    "unit_replace_at_ref",
    "unit_rewrite_at_ref",
    "unit_substitute",
]
