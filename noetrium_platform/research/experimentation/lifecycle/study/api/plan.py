"""Deterministic compiled experiment-plan boundary.

The plan freezes protocol, provider bindings, and the complete assignment matrix.
Execution consumes this projection; project-specific names and factor semantics
never become runtime authority.
"""
from __future__ import annotations

from noetrium_platform.foundation.kernel.structure import structure_unit


from noetrium_platform.research.experimentation.lifecycle.study.api.contracts import (
    STUDY_VARIANT_SPACE_TRAIT,
    VariantKind,
    assignment_workload_digest,
    study_variant_graph,
    study_variant_configuration_digest,
    study_protocol_variant_space,
    study_protocol_variant_count,
    study_protocol_workloads,
    study_protocol_text,
    study_protocol_repetitions,
    study_assignment,
    study_assignment_variant_index,
)

from dataclasses import dataclass, field
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256



@dataclass(frozen=True, slots=True)
class VariantBinding:
    variant: NoetriumUnit
    intervention_digest: str
    provider_id: str
    ablation_policy_id: str
    comparator_role: str
    binding_digest: str = field(init=False)

    @classmethod
    def from_inputs(
        cls,
        *,
        variant: NoetriumUnit,
        intervention: object,
        provider_id: str,
        ablation_policy_id: str,
        comparator_role: str,
    ) -> "VariantBinding":
        return cls(
            variant=variant,
            intervention_digest=canonical_digest(intervention),
            provider_id=provider_id,
            ablation_policy_id=ablation_policy_id,
            comparator_role=comparator_role,
        )

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


def study_variant_space(
    factors: tuple[NoetriumUnit, ...],
    *,
    implementation_id: str,
    budget_tier: str | None,
) -> NoetriumUnit:
    from .unit_semantics import factor_levels

    if type(factors) is not tuple:
        raise TypeError("study variant space factors must be a tuple")
    if type(implementation_id) is not str or not implementation_id.strip():
        raise ValueError("study variant space implementation_id is required")
    if budget_tier is not None and (
        type(budget_tier) is not str or not budget_tier.strip()
    ):
        raise ValueError("study variant space budget_tier must be canonical text")
    level_counts: list[int] = []
    members: list[NoetriumUnit] = []
    factor_ids: list[str] = []
    variant_count = 1
    for index, factor in enumerate(factors):
        levels = factor_levels(factor)
        if not levels:
            raise ValueError("study variant factor requires at least one level")
        factor_ids.append(factor.unit_id)
        level_counts.append(len(levels))
        variant_count *= len(levels)
        members.append(
            structure_unit(
                f"axis:{index}",
                traits=("study.variant-axis",),
                parameters={"level_count": len(levels)},
                members=(factor,),
            )
        )
    if len(factor_ids) != len(set(factor_ids)):
        raise ValueError("study variant space factor identities must be unique")
    descriptor = {
        "schema": "noetrium.study-variant-space.v1",
        "implementation_id": implementation_id,
        "budget_tier": budget_tier,
        "factor_digests": tuple(row.unit_digest for row in factors),
        "level_counts": tuple(level_counts),
        "variant_count": variant_count,
    }
    return structure_unit(
        "variant-space:" + canonical_digest(descriptor)[:20],
        traits=(STUDY_VARIANT_SPACE_TRAIT,),
        parameters={
            **descriptor,
            "factor_count": len(factors),
        },
        members=tuple(members),
    )


def _require_variant_space(space: NoetriumUnit) -> NoetriumUnit:
    if type(space) is not NoetriumUnit or not space.has_trait(STUDY_VARIANT_SPACE_TRAIT):
        raise TypeError("study variant space must be NoetriumUnit")
    count = space.parameters.get("variant_count")
    if type(count) is not int or count <= 0:
        raise ValueError("study variant space requires positive variant_count")
    return space


def study_variant_space_count(space: NoetriumUnit) -> int:
    return int(_require_variant_space(space).parameters["variant_count"])


def _study_variant_space_factors(space: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    space = _require_variant_space(space)
    count = int(space.parameters["factor_count"])
    return tuple(space.member(f"axis:{index}").members[0] for index in range(count))


def study_variant_space_intervention_at(
    space: NoetriumUnit,
    index: int,
) -> NoetriumUnit:
    from .unit_semantics import (
        factor_levels,
        factor_level_control,
        factor_selection_unit,
        intervention_unit,
    )

    count = study_variant_space_count(space)
    if type(index) is not int or index < 0 or index >= count:
        raise IndexError("study variant index out of range")
    factors = _study_variant_space_factors(space)
    if not factors:
        return intervention_unit("control", ())
    remaining = index
    selected_reversed: list[tuple[NoetriumUnit, NoetriumUnit]] = []
    for factor in reversed(factors):
        levels = factor_levels(factor)
        remaining, level_index = divmod(remaining, len(levels))
        selected_reversed.append((factor, levels[level_index]))
    selected = tuple(reversed(selected_reversed))
    selections = tuple(
        factor_selection_unit(factor, level)
        for factor, level in selected
    )
    control = all(factor_level_control(level) for _, level in selected)
    selection_digest = canonical_digest(tuple(row.unit_digest for row in selections))
    intervention_id = "control" if control else f"intervention-{selection_digest[:16]}"
    return intervention_unit(intervention_id, selections)


def study_variant_space_variant_at(
    space: NoetriumUnit,
    index: int,
) -> NoetriumUnit:
    from .unit_semantics import intervention_control, intervention_digest

    space = _require_variant_space(space)
    intervention = study_variant_space_intervention_at(space, index)
    budget_tier = space.parameters.get("budget_tier")
    return study_variant_graph(
        variant_id=intervention.unit_id,
        kind=(
            VariantKind.CONTROL
            if intervention_control(intervention)
            else VariantKind.TREATMENT
        ),
        implementation_id=str(space.parameters["implementation_id"]),
        configuration_digest=intervention_digest(intervention),
        budget_tier=None if budget_tier is None else str(budget_tier),
    )


def study_variant_space_binding_at(
    space: NoetriumUnit,
    index: int,
) -> VariantBinding:
    variant = study_variant_space_variant_at(space, index)
    return VariantBinding(
        variant,
        study_variant_configuration_digest(variant),
        str(_require_variant_space(space).parameters["implementation_id"]),
        "none",
        str(variant.parameters["kind"]),
    )


def study_variant_space_binding_digest(space: NoetriumUnit) -> str:
    space = _require_variant_space(space)
    return canonical_digest(
        {
            "schema": "noetrium.study-variant-binding-space.v1",
            "variant_space_digest": space.unit_digest,
            "provider_id": space.parameters["implementation_id"],
            "ablation_policy_id": "none",
            "comparator_semantics": "variant.kind",
        }
    )


def _assignment_matrix_descriptor(
    protocol: NoetriumUnit,
    seeds: tuple[str, ...],
) -> dict[str, object]:
    from .contracts import require_study_protocol
    require_study_protocol(protocol)
    if type(seeds) is not tuple or not seeds or any(
        type(seed) is not str or not seed.strip() or seed != seed.strip()
        for seed in seeds
    ):
        raise TypeError("study assignment seeds must be canonical non-empty text tuple")
    if len(seeds) != len(set(seeds)):
        raise ValueError("study assignment seeds must be unique")
    variant_space = study_protocol_variant_space(protocol)
    variant_count = study_protocol_variant_count(protocol)
    workloads = study_protocol_workloads(protocol)
    repetitions = study_protocol_repetitions(protocol)
    if variant_count <= 0 or not workloads or repetitions <= 0:
        raise ValueError("study assignment matrix requires variants, workloads and repetitions")
    return {
        "schema": "noetrium.study-assignment-matrix.v2",
        "study_id": study_protocol_text(protocol, "study_id"),
        "variant_space_digest": variant_space.unit_digest,
        "variant_count": variant_count,
        "workload_digests": tuple(assignment_workload_digest(row) for row in workloads),
        "repetitions": repetitions,
        "seeds": seeds,
        "assignment_count": repetitions * len(seeds) * variant_count * len(workloads),
    }


def _assignment_matrix_digest(protocol: NoetriumUnit, seeds: tuple[str, ...]) -> str:
    return canonical_digest(_assignment_matrix_descriptor(protocol, seeds))




STUDY_EXECUTION_PLAN_TRAIT = "study.execution-plan"

def study_execution_plan(
    protocol: NoetriumUnit,
    *,
    seeds: tuple[str, ...],
) -> NoetriumUnit:
    from .contracts import require_study_protocol
    require_study_protocol(protocol)
    variant_space = study_protocol_variant_space(protocol)
    matrix = _assignment_matrix_descriptor(protocol, seeds)
    matrix_digest = canonical_digest(matrix)
    binding_space_digest = study_variant_space_binding_digest(variant_space)
    return structure_unit(
        "study-plan:"
        + canonical_digest(
            (
                protocol.semantic_digest,
                binding_space_digest,
                matrix_digest,
            )
        )[:20],
        traits=(STUDY_EXECUTION_PLAN_TRAIT,),
        parameters={
            "variant_count": study_variant_space_count(variant_space),
            "binding_space_digest": binding_space_digest,
            "assignment_count": int(matrix["assignment_count"]),
            "assignment_seeds": seeds,
            "assignment_matrix_digest": matrix_digest,
        },
        members=(
            structure_unit(
                "protocol",
                traits=("study.plan-protocol",),
                members=(protocol,),
            ),
        ),
    )

def require_study_execution_plan(plan: NoetriumUnit)->NoetriumUnit:
    if type(plan) is not NoetriumUnit or not plan.has_trait(STUDY_EXECUTION_PLAN_TRAIT): raise TypeError("study execution plan must be NoetriumUnit")
    return plan

def study_plan_protocol(plan: NoetriumUnit) -> NoetriumUnit:
    require_study_execution_plan(plan)
    return plan.member("protocol").members[0]


def study_plan_variant_space(plan: NoetriumUnit) -> NoetriumUnit:
    return study_protocol_variant_space(study_plan_protocol(plan))


def study_plan_variant_count(plan: NoetriumUnit) -> int:
    require_study_execution_plan(plan)
    count = study_variant_space_count(study_plan_variant_space(plan))
    if count != int(plan.parameters["variant_count"]):
        raise ValueError("study plan variant count drifted")
    return count


def study_plan_variant_at(plan: NoetriumUnit, index: int) -> NoetriumUnit:
    return study_variant_space_variant_at(study_plan_variant_space(plan), index)


def study_plan_intervention_at(plan: NoetriumUnit, index: int) -> NoetriumUnit:
    return study_variant_space_intervention_at(study_plan_variant_space(plan), index)


def study_plan_binding_at(plan: NoetriumUnit, index: int) -> VariantBinding:
    return study_variant_space_binding_at(study_plan_variant_space(plan), index)


def study_plan_provider_id(plan: NoetriumUnit) -> str:
    return str(study_plan_variant_space(plan).parameters["implementation_id"])


def study_plan_assignment_matrix(plan: NoetriumUnit) -> dict[str, object]:
    require_study_execution_plan(plan)
    protocol = study_plan_protocol(plan)
    seeds = tuple(plan.parameters["assignment_seeds"])
    matrix = _assignment_matrix_descriptor(protocol, seeds)
    if canonical_digest(matrix) != str(plan.parameters["assignment_matrix_digest"]):
        raise ValueError("study assignment matrix digest drifted")
    if int(matrix["assignment_count"]) != int(plan.parameters["assignment_count"]):
        raise ValueError("study assignment matrix count drifted")
    return matrix


def study_plan_assignment_count(plan: NoetriumUnit) -> int:
    return int(study_plan_assignment_matrix(plan)["assignment_count"])


def study_plan_assignment_at(plan: NoetriumUnit, index: int) -> NoetriumUnit:
    count = study_plan_assignment_count(plan)
    if type(index) is not int or index < 0 or index >= count:
        raise IndexError("study assignment index out of range")
    protocol = study_plan_protocol(plan)
    seeds = tuple(plan.parameters["assignment_seeds"])
    variant_count = study_plan_variant_count(plan)
    workloads = study_protocol_workloads(protocol)
    per_seed = variant_count * len(workloads)
    per_repetition = len(seeds) * per_seed
    repetition, offset = divmod(index, per_repetition)
    seed_index, offset = divmod(offset, per_seed)
    variant_index, workload_index = divmod(offset, len(workloads))
    variant = study_plan_variant_at(plan, variant_index)
    return study_assignment(
        study_protocol_text(protocol, "study_id"),
        variant.unit_id,
        variant_index,
        repetition,
        seeds[seed_index],
        workloads[workload_index],
    )


def iter_study_plan_assignment_range(
    plan: NoetriumUnit,
    start: int = 0,
    stop: int | None = None,
):
    count = study_plan_assignment_count(plan)
    if type(start) is not int or start < 0 or start > count:
        raise ValueError("study assignment range start is invalid")
    resolved_stop = count if stop is None else stop
    if (
        type(resolved_stop) is not int
        or resolved_stop < start
        or resolved_stop > count
    ):
        raise ValueError("study assignment range stop is invalid")
    for index in range(start, resolved_stop):
        yield study_plan_assignment_at(plan, index)


def iter_study_plan_assignments(plan: NoetriumUnit):
    yield from iter_study_plan_assignment_range(plan)


def study_plan_assignments(plan: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    return tuple(iter_study_plan_assignments(plan))


def study_plan_digest(plan:NoetriumUnit)->str: require_study_execution_plan(plan); return plan.semantic_digest
def study_plan_binding_digest(plan: NoetriumUnit) -> str:
    require_study_execution_plan(plan)
    digest = study_variant_space_binding_digest(study_plan_variant_space(plan))
    if digest != str(plan.parameters["binding_space_digest"]):
        raise ValueError("study plan binding space digest drifted")
    return digest
def study_plan_assignment_digest(plan: NoetriumUnit) -> str:
    require_study_execution_plan(plan)
    protocol = study_plan_protocol(plan)
    seeds = tuple(plan.parameters["assignment_seeds"])
    digest = _assignment_matrix_digest(protocol, seeds)
    if digest != str(plan.parameters["assignment_matrix_digest"]):
        raise ValueError("study assignment matrix digest drifted")
    return digest



__all__ = [
    "STUDY_VARIANT_SPACE_TRAIT",
    "STUDY_EXECUTION_PLAN_TRAIT",
    "study_variant_space",
    "study_variant_space_count",
    "study_variant_space_intervention_at",
    "study_variant_space_variant_at",
    "study_variant_space_binding_at",
    "study_variant_space_binding_digest",
    "study_execution_plan",
    "require_study_execution_plan",
    "study_plan_protocol",
    "study_plan_variant_space",
    "study_plan_variant_count",
    "study_plan_variant_at",
    "study_plan_intervention_at",
    "study_plan_binding_at",
    "study_plan_provider_id",
    "study_plan_assignment_matrix",
    "study_plan_assignment_count",
    "study_plan_assignment_at",
    "iter_study_plan_assignment_range",
    "iter_study_plan_assignments",
    "study_plan_assignments",
    "study_plan_digest",
    "study_plan_binding_digest",
    "study_plan_assignment_digest",
    "VariantBinding",
]
