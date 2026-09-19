"""Deterministic compiled experiment-plan boundary.

The plan freezes protocol, provider bindings, and the complete assignment matrix.
Execution consumes this projection; project-specific names and factor semantics
never become runtime authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256

from .contracts import (
    StudyAssignment,
    StudyExecutionUnit,
    StudyProtocol,
    StudyVariantSpec,
)


class VariantExecutionProvider(Protocol):
    def provider_id(self) -> str: ...


@dataclass(frozen=True, slots=True)
class VariantBinding:
    variant: StudyVariantSpec
    intervention_digest: str
    provider_id: str
    ablation_policy_id: str
    comparator_role: str
    binding_digest: str = field(init=False)
    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (
                self.intervention_digest,
                self.provider_id,
                self.ablation_policy_id,
                self.comparator_role,
            )
        ):
            raise ValueError("variant binding identity is incomplete")
        require_sha256(self.intervention_digest, "variant binding intervention_digest")
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest(
                {
                    "variant": self.variant,
                    "intervention_digest": self.intervention_digest,
                    "provider_id": self.provider_id,
                    "ablation_policy_id": self.ablation_policy_id,
                    "comparator_role": self.comparator_role,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class VariantExecutionRequest:
    """The only runtime request a variant provider is allowed to consume."""

    plan_digest: str
    unit: StudyExecutionUnit
    assignment: StudyAssignment
    binding: VariantBinding
    def __post_init__(self) -> None:
        require_sha256(self.plan_digest, "variant execution request plan_digest")
        if self.assignment not in self.unit.assignments:
            raise ValueError("variant execution request assignment is outside its unit")
        if self.assignment.variant_id != self.binding.variant.variant_id:
            raise ValueError("variant execution request binding does not match assignment")


def _require_plan_assignments(
    protocol: StudyProtocol,
    assignments: object,
) -> tuple[StudyAssignment, ...]:
    if type(assignments) is not tuple or not assignments:
        raise TypeError("experiment plan assignments must be a non-empty tuple")
    if any(type(item) is not StudyAssignment for item in assignments):
        raise TypeError("experiment plan assignments must contain StudyAssignment")
    if len({item.assignment_digest for item in assignments}) != len(assignments):
        raise ValueError("experiment plan assignments must be unique")
    declared = {item.variant_id for item in protocol.variants}
    seen_by_repetition: dict[int, set[str]] = {}
    for item in assignments:
        if item.study_id != protocol.study_id:
            raise ValueError("experiment plan assignment belongs to another study")
        if item.variant_id not in declared:
            raise ValueError("experiment plan assignment references an undeclared variant")
        if item.repetition >= protocol.repetitions:
            raise ValueError("experiment plan assignment repetition exceeds protocol")
        seen_by_repetition.setdefault(item.repetition, set()).add(item.variant_id)
    if set(seen_by_repetition) != set(range(protocol.repetitions)):
        raise ValueError("experiment plan assignments do not cover every repetition")
    if any(variants != declared for variants in seen_by_repetition.values()):
        raise ValueError("experiment plan assignments do not cover every variant per repetition")
    return assignments


def _assignment_matrix_digest(assignments: tuple[StudyAssignment, ...]) -> str:
    return canonical_digest(tuple(item.assignment_digest for item in assignments))


@dataclass(frozen=True, slots=True)
class ExperimentPlan:
    protocol: StudyProtocol
    bindings: tuple[VariantBinding, ...]
    assignments: tuple[StudyAssignment, ...]
    plan_digest: str
    protocol_digest: str = field(init=False)
    binding_digest: str = field(init=False)
    assignment_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.bindings) is not tuple:
            raise TypeError("experiment plan bindings must be a tuple")
        if tuple(item.variant for item in self.bindings) != self.protocol.variants:
            raise ValueError("experiment plan bindings must exactly follow protocol variant order")
        assignments = _require_plan_assignments(self.protocol, self.assignments)
        protocol_digest = self.protocol.protocol_digest
        binding_digest = canonical_digest(tuple(item.binding_digest for item in self.bindings))
        assignment_digest = _assignment_matrix_digest(assignments)
        expected_plan_digest = canonical_digest(
            {
                "protocol_digest": protocol_digest,
                "binding_digest": binding_digest,
                "assignment_digest": assignment_digest,
            }
        )
        if self.plan_digest != expected_plan_digest:
            raise ValueError("experiment plan digest is not authoritative")
        object.__setattr__(self, "protocol_digest", protocol_digest)
        object.__setattr__(self, "binding_digest", binding_digest)
        object.__setattr__(self, "assignment_digest", assignment_digest)

    @classmethod
    def compile(
        cls,
        protocol: StudyProtocol,
        bindings: tuple[VariantBinding, ...],
        assignments: tuple[StudyAssignment, ...],
    ) -> "ExperimentPlan":
        binding_digest = canonical_digest(tuple(item.binding_digest for item in bindings))
        assignment_digest = _assignment_matrix_digest(assignments)
        return cls(
            protocol,
            bindings,
            assignments,
            canonical_digest(
                {
                    "protocol_digest": protocol.protocol_digest,
                    "binding_digest": binding_digest,
                    "assignment_digest": assignment_digest,
                }
            ),
        )

    def assert_consistent(self) -> None:
        expected = type(self).compile(self.protocol, self.bindings, self.assignments)
        if expected.protocol_digest != self.protocol_digest:
            raise ValueError("experiment plan protocol digest drifted")
        if expected.binding_digest != self.binding_digest:
            raise ValueError("experiment plan binding digest drifted")
        if expected.assignment_digest != self.assignment_digest:
            raise ValueError("experiment plan assignment digest drifted")
        if expected.plan_digest != self.plan_digest:
            raise ValueError("experiment plan digest drifted")

    def binding_for(self, variant_id: str) -> VariantBinding:
        matches = tuple(
            item for item in self.bindings if item.variant.variant_id == variant_id
        )
        if len(matches) != 1:
            raise KeyError(f"experiment plan has no unique binding for {variant_id!r}")
        return matches[0]


__all__ = [
    "ExperimentPlan",
    "VariantBinding",
    "VariantExecutionProvider",
    "VariantExecutionRequest",
]
