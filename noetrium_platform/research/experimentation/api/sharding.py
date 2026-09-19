"""Deterministic cross-worker sharding for compiled experiment plans.

This module partitions immutable StudyAssignment identities for server-scale
execution. It owns no scientific semantics and does not execute work. A shard
plan is a deployment projection over an authoritative ExperimentPlan: changing
worker count or cost estimates changes only placement, never trial identity,
benchmark membership, treatment, seed, repetition, or measurements.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from noetrium_platform.foundation.kernel.kernel import (
    canonical_digest,
    require_sha256,
)
from noetrium_platform.research.experimentation.study.api.plan import ExperimentPlan


def _positive_int(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{field_name} must be an integer")
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return value


@dataclass(frozen=True, slots=True)
class ExperimentShard:
    shard_index: int
    worker_scope_id: str
    assignment_digests: tuple[str, ...]
    estimated_cost_units: int
    shard_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.shard_index) is not int or self.shard_index < 0:
            raise ValueError("experiment shard_index must be a non-negative integer")
        if type(self.worker_scope_id) is not str or not self.worker_scope_id.strip():
            raise ValueError("experiment worker_scope_id must be non-empty")
        if type(self.assignment_digests) is not tuple:
            raise TypeError("experiment shard assignment_digests must be a tuple")
        if len(self.assignment_digests) != len(set(self.assignment_digests)):
            raise ValueError("experiment shard assignments must be unique")
        for digest in self.assignment_digests:
            require_sha256(digest, "experiment shard assignment digest")
        if type(self.estimated_cost_units) is not int or self.estimated_cost_units < 0:
            raise ValueError(
                "experiment shard estimated_cost_units must be non-negative"
            )
        object.__setattr__(
            self,
            "shard_digest",
            canonical_digest(
                {
                    "shard_index": self.shard_index,
                    "worker_scope_id": self.worker_scope_id,
                    "assignment_digests": self.assignment_digests,
                    "estimated_cost_units": self.estimated_cost_units,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class CompiledExperimentShardPlan:
    experiment_plan_digest: str
    shard_count: int
    cost_model_digest: str
    shards: tuple[ExperimentShard, ...]
    shard_plan_digest: str = field(init=False)

    def __post_init__(self) -> None:
        require_sha256(
            self.experiment_plan_digest,
            "experiment shard plan experiment_plan_digest",
        )
        _positive_int(self.shard_count, "experiment shard plan shard_count")
        require_sha256(
            self.cost_model_digest,
            "experiment shard plan cost_model_digest",
        )
        if type(self.shards) is not tuple or len(self.shards) != self.shard_count:
            raise ValueError(
                "experiment shard plan must contain exactly shard_count shards"
            )
        if tuple(row.shard_index for row in self.shards) != tuple(
            range(self.shard_count)
        ):
            raise ValueError("experiment shard indices must be canonical")
        digests = tuple(
            assignment
            for shard in self.shards
            for assignment in shard.assignment_digests
        )
        if len(digests) != len(set(digests)):
            raise ValueError("experiment shard plan assignments must be disjoint")
        object.__setattr__(
            self,
            "shard_plan_digest",
            canonical_digest(
                {
                    "experiment_plan_digest": self.experiment_plan_digest,
                    "shard_count": self.shard_count,
                    "cost_model_digest": self.cost_model_digest,
                    "shards": tuple(row.shard_digest for row in self.shards),
                }
            ),
        )

    @property
    def assignment_digests(self) -> tuple[str, ...]:
        return tuple(
            assignment
            for shard in self.shards
            for assignment in shard.assignment_digests
        )

    def shard(self, shard_index: int) -> ExperimentShard:
        if type(shard_index) is not int:
            raise TypeError("experiment shard index must be an integer")
        if shard_index < 0 or shard_index >= self.shard_count:
            raise IndexError("experiment shard index is outside the compiled plan")
        return self.shards[shard_index]

    def assert_complete_for(self, plan: ExperimentPlan) -> None:
        if type(plan) is not ExperimentPlan:
            raise TypeError("experiment shard validation requires ExperimentPlan")
        plan.assert_consistent()
        if plan.plan_digest != self.experiment_plan_digest:
            raise ValueError("experiment shard plan belongs to another ExperimentPlan")
        expected = {row.assignment_digest for row in plan.assignments}
        actual = set(self.assignment_digests)
        if actual != expected or len(self.assignment_digests) != len(expected):
            raise ValueError(
                "experiment shard plan does not exactly cover plan assignments"
            )


def compile_experiment_shard_plan(
    plan: ExperimentPlan,
    *,
    shard_count: int,
    assignment_cost_units: Mapping[str, int] | None = None,
) -> CompiledExperimentShardPlan:
    """Compile a deterministic load-balanced cross-worker partition.

    Assignments are sorted by descending estimated cost, then immutable
    assignment digest. Each item is placed onto the currently least-loaded shard
    with shard index as the deterministic tie-breaker (LPT scheduling).

    The optional assignment cost mapping is deployment metadata only. It must
    cover either zero assignments (uniform cost=1) or exactly the authoritative
    assignment set; partial cost models are rejected.
    """

    if type(plan) is not ExperimentPlan:
        raise TypeError("experiment sharding requires ExperimentPlan")
    plan.assert_consistent()
    shard_count = _positive_int(shard_count, "experiment shard_count")

    assignment_by_digest = {
        row.assignment_digest: row for row in plan.assignments
    }
    expected = set(assignment_by_digest)
    if assignment_cost_units is None:
        costs = {digest: 1 for digest in expected}
        cost_model_kind = "uniform-v1"
    else:
        if not isinstance(assignment_cost_units, Mapping):
            raise TypeError("assignment_cost_units must be a mapping")
        if set(assignment_cost_units) != expected:
            missing = tuple(sorted(expected - set(assignment_cost_units)))
            extra = tuple(sorted(set(assignment_cost_units) - expected))
            raise ValueError(
                "assignment cost model must exactly cover plan assignments "
                f"(missing={missing}, extra={extra})"
            )
        costs = {
            digest: _positive_int(
                assignment_cost_units[digest],
                f"assignment cost for {digest}",
            )
            for digest in expected
        }
        cost_model_kind = "explicit-integer-cost-v1"

    cost_model_digest = canonical_digest(
        {
            "kind": cost_model_kind,
            "assignment_cost_units": tuple(
                (digest, costs[digest]) for digest in sorted(costs)
            ),
        }
    )

    assignment_rows = sorted(
        plan.assignments,
        key=lambda row: (-costs[row.assignment_digest], row.assignment_digest),
    )
    shard_rows: list[list[str]] = [[] for _ in range(shard_count)]
    shard_costs = [0 for _ in range(shard_count)]

    for assignment in assignment_rows:
        target = min(
            range(shard_count),
            key=lambda index: (shard_costs[index], index),
        )
        digest = assignment.assignment_digest
        shard_rows[target].append(digest)
        shard_costs[target] += costs[digest]

    scope_prefix = f"experiment-shard:{plan.plan_digest[:16]}"
    shards = tuple(
        ExperimentShard(
            shard_index=index,
            worker_scope_id=f"{scope_prefix}:{index}",
            assignment_digests=tuple(shard_rows[index]),
            estimated_cost_units=shard_costs[index],
        )
        for index in range(shard_count)
    )
    compiled = CompiledExperimentShardPlan(
        experiment_plan_digest=plan.plan_digest,
        shard_count=shard_count,
        cost_model_digest=cost_model_digest,
        shards=shards,
    )
    compiled.assert_complete_for(plan)
    return compiled


__all__ = [
    "CompiledExperimentShardPlan",
    "ExperimentShard",
    "compile_experiment_shard_plan",
]
