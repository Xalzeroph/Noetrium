"""Deterministic worker placement for compiled ExperimentProgram batches.

Cross-worker sharding is deliberately a deployment projection, never a second
scientific scheduler. The authoritative CompiledExperimentProgram freezes batch
order and allowed concurrency. This module only assigns immutable assignment
identities to worker scopes, then projects each authoritative batch through that
placement.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from noetrium_platform.foundation.kernel.kernel import (
    canonical_digest,
    require_sha256,
)
from noetrium_platform.research.experimentation.api.program import (
    CompiledExperimentProgram,
    ExperimentBatch,
)


def _positive_int(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{field_name} must be an integer")
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return value


@dataclass(frozen=True, slots=True)
class ExperimentShard:
    """Stable worker placement for a disjoint assignment subset."""

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
class ExperimentBatchPlacement:
    """One authoritative ExperimentBatch projected onto worker shards."""

    batch_id: str
    batch_digest: str
    shard_assignments: tuple[tuple[int, tuple[str, ...]], ...]
    placement_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.batch_id) is not str or not self.batch_id.strip():
            raise ValueError("experiment batch placement batch_id must be non-empty")
        require_sha256(
            self.batch_digest,
            "experiment batch placement batch_digest",
        )
        if type(self.shard_assignments) is not tuple:
            raise TypeError("batch shard_assignments must be a tuple")
        indices = tuple(row[0] for row in self.shard_assignments)
        if indices != tuple(sorted(indices)) or len(indices) != len(set(indices)):
            raise ValueError("batch shard assignments must be canonically ordered")
        flattened: list[str] = []
        for shard_index, assignments in self.shard_assignments:
            if type(shard_index) is not int or shard_index < 0:
                raise ValueError("batch shard index must be non-negative")
            if type(assignments) is not tuple or not assignments:
                raise ValueError("batch shard placement requires assignments")
            for digest in assignments:
                require_sha256(digest, "batch shard assignment digest")
            flattened.extend(assignments)
        if len(flattened) != len(set(flattened)):
            raise ValueError("batch shard placement assignments must be disjoint")
        object.__setattr__(
            self,
            "placement_digest",
            canonical_digest(
                {
                    "batch_id": self.batch_id,
                    "batch_digest": self.batch_digest,
                    "shard_assignments": self.shard_assignments,
                }
            ),
        )

    @property
    def assignment_digests(self) -> tuple[str, ...]:
        return tuple(
            digest
            for _, assignments in self.shard_assignments
            for digest in assignments
        )


@dataclass(frozen=True, slots=True)
class CompiledExperimentShardPlan:
    """Worker placement bound to one exact compiled batch plan."""

    experiment_plan_digest: str
    batch_plan_digest: str
    shard_count: int
    cost_model_digest: str
    shards: tuple[ExperimentShard, ...]
    batch_placements: tuple[ExperimentBatchPlacement, ...]
    shard_plan_digest: str = field(init=False)

    def __post_init__(self) -> None:
        require_sha256(
            self.experiment_plan_digest,
            "experiment shard plan experiment_plan_digest",
        )
        require_sha256(
            self.batch_plan_digest,
            "experiment shard plan batch_plan_digest",
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
        if type(self.batch_placements) is not tuple or not self.batch_placements:
            raise ValueError("experiment shard plan requires batch placements")
        object.__setattr__(
            self,
            "shard_plan_digest",
            canonical_digest(
                {
                    "experiment_plan_digest": self.experiment_plan_digest,
                    "batch_plan_digest": self.batch_plan_digest,
                    "shard_count": self.shard_count,
                    "cost_model_digest": self.cost_model_digest,
                    "shards": tuple(row.shard_digest for row in self.shards),
                    "batch_placements": tuple(
                        row.placement_digest for row in self.batch_placements
                    ),
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

    def placement_for_batch(self, batch_index: int) -> ExperimentBatchPlacement:
        if type(batch_index) is not int:
            raise TypeError("experiment batch index must be an integer")
        if batch_index < 0 or batch_index >= len(self.batch_placements):
            raise IndexError("experiment batch index is outside the compiled plan")
        return self.batch_placements[batch_index]

    def worker_scope_for_assignment(self, assignment_digest: str) -> str:
        require_sha256(
            assignment_digest,
            "experiment shard lookup assignment_digest",
        )
        matches = tuple(
            shard.worker_scope_id
            for shard in self.shards
            if assignment_digest in shard.assignment_digests
        )
        if len(matches) != 1:
            raise KeyError("assignment has no unique experiment worker placement")
        return matches[0]

    def assert_complete_for(self, compiled: CompiledExperimentProgram) -> None:
        if type(compiled) is not CompiledExperimentProgram:
            raise TypeError(
                "experiment shard validation requires CompiledExperimentProgram"
            )
        _assert_compiled_batch_authority(compiled)
        if compiled.plan.plan_digest != self.experiment_plan_digest:
            raise ValueError(
                "experiment shard plan belongs to another ExperimentPlan"
            )
        if compiled.batch_plan_digest != self.batch_plan_digest:
            raise ValueError(
                "experiment shard plan belongs to another batch plan"
            )

        expected = {row.assignment_digest for row in compiled.plan.assignments}
        actual = set(self.assignment_digests)
        if actual != expected or len(self.assignment_digests) != len(expected):
            raise ValueError(
                "experiment shard plan does not exactly cover plan assignments"
            )
        if len(self.batch_placements) != len(compiled.batches):
            raise ValueError(
                "experiment shard plan does not preserve authoritative batch count"
            )
        for placement, batch in zip(
            self.batch_placements,
            compiled.batches,
            strict=True,
        ):
            if placement.batch_id != batch.batch_id:
                raise ValueError("experiment batch placement id drifted")
            if placement.batch_digest != batch.batch_digest:
                raise ValueError("experiment batch placement digest drifted")
            if (
                set(placement.assignment_digests) != set(batch.assignment_digests)
                or len(placement.assignment_digests)
                != len(batch.assignment_digests)
            ):
                raise ValueError(
                    "experiment batch placement does not exactly preserve batch"
                )
            if any(
                shard_index >= self.shard_count
                for shard_index, _ in placement.shard_assignments
            ):
                raise ValueError(
                    "experiment batch placement references unknown shard"
                )


def _assert_compiled_batch_authority(
    compiled: CompiledExperimentProgram,
) -> None:
    expected_batch_plan_digest = canonical_digest(
        tuple(batch.batch_digest for batch in compiled.batches)
    )
    if compiled.batch_plan_digest != expected_batch_plan_digest:
        raise ValueError("compiled ExperimentProgram batch plan digest drifted")
    expected_assignments = {
        row.assignment_digest for row in compiled.plan.assignments
    }
    scheduled = tuple(
        digest
        for batch in compiled.batches
        for digest in batch.assignment_digests
    )
    if (
        len(scheduled) != len(set(scheduled))
        or set(scheduled) != expected_assignments
    ):
        raise ValueError(
            "compiled ExperimentProgram batches do not exactly cover assignments"
        )


def _batch_placement(
    batch: ExperimentBatch,
    *,
    assignment_to_shard: Mapping[str, int],
    shard_count: int,
) -> ExperimentBatchPlacement:
    per_shard: list[list[str]] = [[] for _ in range(shard_count)]
    for digest in batch.assignment_digests:
        try:
            shard_index = assignment_to_shard[digest]
        except KeyError as exc:
            raise ValueError(
                "experiment batch references unplaced assignment"
            ) from exc
        per_shard[shard_index].append(digest)
    return ExperimentBatchPlacement(
        batch_id=batch.batch_id,
        batch_digest=batch.batch_digest,
        shard_assignments=tuple(
            (index, tuple(rows))
            for index, rows in enumerate(per_shard)
            if rows
        ),
    )


def compile_experiment_shard_plan(
    compiled: CompiledExperimentProgram,
    *,
    shard_count: int,
    assignment_cost_units: Mapping[str, int] | None = None,
) -> CompiledExperimentShardPlan:
    """Compile deterministic worker placement without changing batch semantics.

    Assignments are globally placed with deterministic LPT balancing. Every
    authoritative ExperimentBatch is then projected through that fixed mapping.
    A server coordinator must dispatch batch_placements in the existing batch
    order; shards are routing destinations, not independent schedulers.

    Cost hints are deployment metadata only. A supplied mapping must exactly
    cover all authoritative assignments so workers cannot silently disagree.
    """

    if type(compiled) is not CompiledExperimentProgram:
        raise TypeError(
            "experiment sharding requires CompiledExperimentProgram"
        )
    compiled.plan.assert_consistent()
    shard_count = _positive_int(shard_count, "experiment shard_count")

    expected = {
        row.assignment_digest for row in compiled.plan.assignments
    }
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
        compiled.plan.assignments,
        key=lambda row: (
            -costs[row.assignment_digest],
            row.assignment_digest,
        ),
    )
    shard_rows: list[list[str]] = [[] for _ in range(shard_count)]
    shard_costs = [0 for _ in range(shard_count)]
    assignment_to_shard: dict[str, int] = {}

    for assignment in assignment_rows:
        target = min(
            range(shard_count),
            key=lambda index: (shard_costs[index], index),
        )
        digest = assignment.assignment_digest
        shard_rows[target].append(digest)
        shard_costs[target] += costs[digest]
        assignment_to_shard[digest] = target

    scope_prefix = (
        f"experiment-shard:{compiled.batch_plan_digest[:16]}"
    )
    shards = tuple(
        ExperimentShard(
            shard_index=index,
            worker_scope_id=f"{scope_prefix}:{index}",
            assignment_digests=tuple(shard_rows[index]),
            estimated_cost_units=shard_costs[index],
        )
        for index in range(shard_count)
    )
    batch_placements = tuple(
        _batch_placement(
            batch,
            assignment_to_shard=assignment_to_shard,
            shard_count=shard_count,
        )
        for batch in compiled.batches
    )
    result = CompiledExperimentShardPlan(
        experiment_plan_digest=compiled.plan.plan_digest,
        batch_plan_digest=compiled.batch_plan_digest,
        shard_count=shard_count,
        cost_model_digest=cost_model_digest,
        shards=shards,
        batch_placements=batch_placements,
    )
    result.assert_complete_for(compiled)
    return result


__all__ = [
    "CompiledExperimentShardPlan",
    "ExperimentBatchPlacement",
    "ExperimentShard",
    "compile_experiment_shard_plan",
]
