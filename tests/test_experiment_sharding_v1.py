from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.api import (
    compile_experiment_shard_plan,
)
from noetrium_platform.research.experimentation.study.api import (
    ExperimentPlan,
    StudyAssignment,
    StudyConcurrencyPolicy,
    StudyProtocol,
    StudyVariantSpec,
    VariantBinding,
    VariantKind,
)


def _variant(variant_id: str, kind: VariantKind) -> StudyVariantSpec:
    return StudyVariantSpec(
        variant_id=variant_id,
        kind=kind,
        implementation_id=f"impl:{variant_id}",
        configuration_digest=canonical_digest({"variant": variant_id}),
        budget_tier="standard",
    )


def _plan() -> ExperimentPlan:
    variants = (
        _variant("control", VariantKind.CONTROL),
        _variant("treatment", VariantKind.TREATMENT),
    )
    protocol = StudyProtocol(
        study_id="server-sharding-test",
        workload_id="benchmark:test",
        variants=variants,
        repetitions=3,
        seed_schedule_digest=canonical_digest(("0", "1", "2")),
        metric_names=("task_success",),
        task_manifest_digest=canonical_digest(("task-0", "task-1", "task-2")),
        budget_tiers=("standard",),
        concurrency_policy=StudyConcurrencyPolicy.isolated_parallel_v1(
            max_parallel_repetitions=3,
            max_parallel_assignments=8,
            repetition_timeout_seconds=600.0,
        ),
    )
    bindings = tuple(
        VariantBinding(
            variant=variant,
            intervention_digest=canonical_digest(
                {"variant": variant.variant_id, "intervention": "fixed"}
            ),
            provider_id=f"provider:{variant.variant_id}",
            ablation_policy_id="none",
            comparator_role="control"
            if variant.kind is VariantKind.CONTROL
            else "treatment",
        )
        for variant in variants
    )
    assignments = tuple(
        StudyAssignment(
            study_id=protocol.study_id,
            variant_id=variant.variant_id,
            repetition=repetition,
            seed=str(repetition),
            task_id=f"task-{repetition}",
        )
        for repetition in range(3)
        for variant in variants
    )
    return ExperimentPlan.compile(protocol, bindings, assignments)


def test_shard_plan_is_stable_complete_and_disjoint() -> None:
    plan = _plan()

    first = compile_experiment_shard_plan(plan, shard_count=3)
    second = compile_experiment_shard_plan(plan, shard_count=3)

    assert first == second
    assert first.shard_plan_digest == second.shard_plan_digest
    assert len(first.shards) == 3
    assert len(first.assignment_digests) == len(plan.assignments)
    assert set(first.assignment_digests) == {
        row.assignment_digest for row in plan.assignments
    }
    assert len(first.assignment_digests) == len(set(first.assignment_digests))
    assert len({row.worker_scope_id for row in first.shards}) == 3


def test_shard_plan_balances_explicit_heterogeneous_costs() -> None:
    plan = _plan()
    assignments = tuple(plan.assignments)
    weights = (9, 8, 7, 1, 1, 1)
    costs = {
        row.assignment_digest: weight
        for row, weight in zip(assignments, weights, strict=True)
    }

    compiled = compile_experiment_shard_plan(
        plan,
        shard_count=3,
        assignment_cost_units=costs,
    )

    assert tuple(row.estimated_cost_units for row in compiled.shards) == (9, 9, 9)
    compiled.assert_complete_for(plan)


def test_shard_plan_rejects_partial_cost_models() -> None:
    plan = _plan()
    one = plan.assignments[0]

    with pytest.raises(
        ValueError,
        match="exactly cover plan assignments",
    ):
        compile_experiment_shard_plan(
            plan,
            shard_count=2,
            assignment_cost_units={one.assignment_digest: 10},
        )


def test_shard_plan_can_leave_excess_workers_idle_without_identity_loss() -> None:
    plan = _plan()

    compiled = compile_experiment_shard_plan(plan, shard_count=8)

    assert len(compiled.shards) == 8
    assert sum(bool(row.assignment_digests) for row in compiled.shards) == 6
    compiled.assert_complete_for(plan)
