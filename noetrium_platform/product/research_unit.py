"""Pure research projections over the universal NoetriumUnit carrier.

This module owns no persistent class, builder, graph carrier, or serialization
format.  It only derives research-specific views from immutable Unit roots.
"""
from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.unit import NoetriumUnit, UnitRef


def require_research_root(root: NoetriumUnit) -> NoetriumUnit:
    if type(root) is not NoetriumUnit:
        raise TypeError("research root must be NoetriumUnit")
    if not root.has_schema("research.portfolio"):
        raise ValueError("research root requires research.portfolio schema")
    return root


def visible_research_symbols_at_path(
    root: NoetriumUnit,
    path: tuple[str, ...],
) -> tuple[NoetriumUnit, ...]:
    """Project the lexical symbol environment visible at one Unit path."""

    require_research_root(root)
    ref = UnitRef(path)
    if ref.path[0] != root.unit_id:
        raise LookupError(f"research root has no Unit at path {path!r}")
    current = root
    visible = {row.unit_id: row for row in current.symbols}
    for child_id in ref.path[1:]:
        try:
            child = current.member(child_id)
        except LookupError as exc:
            raise LookupError(
                f"research root has no Unit at path {path!r}"
            ) from exc
        child_visible: dict[str, NoetriumUnit] = {}
        for symbol_id in child.symbol_ids:
            try:
                child_visible[symbol_id] = visible[symbol_id]
            except KeyError as exc:
                raise ValueError(
                    f"research Unit path {path!r} has unbound symbol "
                    f"{symbol_id!r}"
                ) from exc
        for symbol in child.symbols:
            if symbol.unit_id in child_visible:
                raise ValueError(
                    f"research Unit {child.unit_id!r} shadows bound symbol "
                    f"{symbol.unit_id!r}"
                )
            child_visible[symbol.unit_id] = symbol
        visible = child_visible
        current = child
    return tuple(visible[key] for key in sorted(visible))


def research_binding_digest(
    root: NoetriumUnit,
    path: tuple[str, ...],
) -> str:
    """Semantic identity of one Unit under its exact bound-symbol environment."""

    unit = require_research_root(root).unit_at_path(path)
    visible = {
        row.unit_id: row
        for row in visible_research_symbols_at_path(root, path)
    }
    return canonical_digest(
        {
            "unit_semantic_digest": unit.semantic_digest,
            "bound_symbols": tuple(
                (symbol_id, visible[symbol_id].semantic_digest)
                for symbol_id in unit.symbol_ids
            ),
        }
    )


__all__ = [
    "require_research_root",
    "research_binding_digest",
    "visible_research_symbols_at_path",
]
