"""Non-destructive rewrite/refinement search over NoetriumUnit."""
from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_digest, freeze_json
from .unit import NoetriumUnit
from .unit_refinement import UnitRefinementWitness


@runtime_checkable
class UnitRewriteRule(Protocol):
    @property
    def rule_id(self) -> str: ...

    @property
    def source_traits(self) -> frozenset[str]: ...

    def rewrite(
        self,
        unit: NoetriumUnit,
        *,
        context: Mapping[str, JsonValue],
    ) -> tuple[NoetriumUnit, ...]: ...


@runtime_checkable
class DeterministicUnitRewrite(Protocol):
    @property
    def rule_id(self) -> str: ...

    @property
    def source_traits(self) -> frozenset[str]: ...

    @property
    def target_traits(self) -> frozenset[str]: ...

    @property
    def identity_digest(self) -> str: ...

    def rewrite_one(
        self,
        unit: NoetriumUnit,
        *,
        context: Mapping[str, JsonValue],
    ) -> NoetriumUnit: ...


def refine_deterministically(
    rule: DeterministicUnitRewrite,
    unit: NoetriumUnit,
    *,
    context: Mapping[str, JsonValue] | None = None,
) -> tuple[NoetriumUnit, UnitRefinementWitness]:
    if not isinstance(rule, DeterministicUnitRewrite):
        raise TypeError("rule must satisfy DeterministicUnitRewrite")
    if type(unit) is not NoetriumUnit:
        raise TypeError("rewrite source must be NoetriumUnit")
    if not rule.source_traits <= unit.trait_ids:
        raise ValueError("deterministic rewrite source traits not satisfied")
    frozen = freeze_json({} if context is None else context)
    if not isinstance(frozen, Mapping):
        raise TypeError("rewrite context must be an object")
    result = rule.rewrite_one(unit, context=frozen)
    if type(result) is not NoetriumUnit or not rule.target_traits <= result.trait_ids:
        raise ValueError("deterministic rewrite target traits not satisfied")
    return result, UnitRefinementWitness.boundary(unit, result)


def deterministic_rewrite_identity(
    rule_id: str,
    source_traits: frozenset[str],
    target_traits: frozenset[str],
    configuration: Mapping[str, JsonValue] | None = None,
) -> str:
    return canonical_digest(
        {
            "rule_id": rule_id,
            "source_traits": tuple(sorted(source_traits)),
            "target_traits": tuple(sorted(target_traits)),
            "configuration": freeze_json({} if configuration is None else configuration),
        }
    )


def apply_unit_rewrite(
    rule: UnitRewriteRule,
    unit: NoetriumUnit,
    *,
    context: Mapping[str, JsonValue] | None = None,
) -> tuple[tuple[NoetriumUnit, UnitRefinementWitness], ...]:
    if not isinstance(rule, UnitRewriteRule):
        raise TypeError("rule must satisfy UnitRewriteRule")
    if type(unit) is not NoetriumUnit:
        raise TypeError("rewrite source must be NoetriumUnit")
    missing = rule.source_traits - unit.trait_ids
    if missing:
        raise ValueError(
            f"rewrite {rule.rule_id!r} missing source traits: {tuple(sorted(missing))}"
        )
    frozen = freeze_json({} if context is None else context)
    if not isinstance(frozen, Mapping):
        raise TypeError("rewrite context must be an object")
    candidates = rule.rewrite(unit, context=frozen)
    if type(candidates) is not tuple or any(
        type(row) is not NoetriumUnit for row in candidates
    ):
        raise TypeError("rewrite must return a NoetriumUnit tuple")
    unique = {row.semantic_digest: row for row in candidates}
    return tuple(
        (row, UnitRefinementWitness.boundary(unit, row))
        for _, row in sorted(unique.items())
    )


def rewrite_frontier(
    unit: NoetriumUnit,
    rules: tuple[UnitRewriteRule, ...],
    *,
    max_rounds: int = 32,
) -> tuple[NoetriumUnit, ...]:
    if type(max_rounds) is not int or max_rounds < 0:
        raise ValueError("max_rounds must be non-negative int")
    known = {unit.semantic_digest: unit}
    frontier = (unit,)
    for _ in range(max_rounds):
        produced: dict[str, NoetriumUnit] = {}
        for current in frontier:
            for rule in rules:
                if rule.source_traits <= current.trait_ids:
                    for candidate, _ in apply_unit_rewrite(rule, current):
                        if candidate.semantic_digest not in known:
                            produced[candidate.semantic_digest] = candidate
        if not produced:
            break
        known.update(produced)
        frontier = tuple(produced[key] for key in sorted(produced))
    return tuple(known[key] for key in sorted(known))


__all__ = [
    "DeterministicUnitRewrite",
    "UnitRewriteRule",
    "apply_unit_rewrite",
    "deterministic_rewrite_identity",
    "refine_deterministically",
    "rewrite_frontier",
]
