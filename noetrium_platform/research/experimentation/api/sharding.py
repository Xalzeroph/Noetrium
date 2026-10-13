"""Deterministic worker placement for compiled ExperimentProgram batches.

Cross-worker sharding is deliberately a deployment projection, never a second
scientific scheduler. The authoritative NoetriumUnit freezes batch
order and allowed concurrency. This module only assigns immutable assignment
identities to worker scopes, then projects each authoritative batch through that
placement.
"""
from __future__ import annotations

from noetrium_platform.foundation.kernel.structure import structure_unit
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.research.experimentation.lifecycle.study.api.plan import require_study_execution_plan, study_plan_assignments, study_plan_digest
from noetrium_platform.research.experimentation.lifecycle.study.api.contracts import study_assignment_digest


from collections.abc import Mapping
from dataclasses import dataclass, field
import heapq

from noetrium_platform.foundation.kernel.kernel import (
    canonical_digest,
    require_sha256,
)
from noetrium_platform.research.experimentation.api.program import (
    ExperimentBatch, experiment_compilation_plan, experiment_compilation_batches, experiment_compilation_batch_digest, require_experiment_compilation,
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
    capacity_units: int = 1
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
        _positive_int(self.capacity_units, "experiment shard capacity_units")
        object.__setattr__(
            self,
            "shard_digest",
            canonical_digest(
                {
                    "shard_index": self.shard_index,
                    "worker_scope_id": self.worker_scope_id,
                    "assignment_digests": self.assignment_digests,
                    "estimated_cost_units": self.estimated_cost_units,
                    "capacity_units": self.capacity_units,
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


EXPERIMENT_SHARD_PLAN_TRAIT = "experiment.shard-plan"

def experiment_shard_plan_graph(experiment_plan_digest: str, batch_plan_digest: str, cost_model_digest: str, shards: tuple[ExperimentShard, ...], placements: tuple[ExperimentBatchPlacement, ...]) -> NoetriumUnit:
    require_sha256(experiment_plan_digest, "experiment shard plan experiment_plan_digest"); require_sha256(batch_plan_digest, "experiment shard plan batch_plan_digest"); require_sha256(cost_model_digest, "experiment shard plan cost_model_digest")
    if not shards or tuple(x.shard_index for x in shards) != tuple(range(len(shards))): raise ValueError("experiment shards must be canonical")
    flat=tuple(d for x in shards for d in x.assignment_digests)
    if len(flat)!=len(set(flat)): raise ValueError("experiment shard assignments must be disjoint")
    if not placements: raise ValueError("experiment shard plan requires placements")
    members=tuple(structure_unit(f"shard:{x.shard_index}", traits=("experiment.shard",), parameters={"worker_scope_id":x.worker_scope_id,"assignment_digests":x.assignment_digests,"estimated_cost_units":x.estimated_cost_units,"capacity_units":x.capacity_units}) for x in shards)+tuple(structure_unit(f"placement:{i}", traits=("experiment.batch-placement",), parameters={"batch_id":x.batch_id,"batch_digest":x.batch_digest,"shard_assignments":x.shard_assignments}) for i,x in enumerate(placements))
    return structure_unit("experiment-shard-plan:"+canonical_digest((experiment_plan_digest,batch_plan_digest,cost_model_digest))[:20], traits=(EXPERIMENT_SHARD_PLAN_TRAIT,), parameters={"experiment_plan_digest":experiment_plan_digest,"batch_plan_digest":batch_plan_digest,"cost_model_digest":cost_model_digest,"shard_count":len(shards),"placement_count":len(placements)}, members=members)

def experiment_shards(g: NoetriumUnit) -> tuple[ExperimentShard,...]:
    if type(g) is not NoetriumUnit or not g.has_trait(EXPERIMENT_SHARD_PLAN_TRAIT): raise TypeError("expected experiment shard graph")
    return tuple(ExperimentShard(i,str((p:=g.member(f"shard:{i}").parameters)["worker_scope_id"]),tuple(p["assignment_digests"]),int(p["estimated_cost_units"]),int(p["capacity_units"])) for i in range(int(g.parameters["shard_count"])))

def experiment_batch_placements(g: NoetriumUnit) -> tuple[ExperimentBatchPlacement,...]:
    if type(g) is not NoetriumUnit or not g.has_trait(EXPERIMENT_SHARD_PLAN_TRAIT): raise TypeError("expected experiment shard graph")
    return tuple(ExperimentBatchPlacement(str((p:=g.member(f"placement:{i}").parameters)["batch_id"]),str(p["batch_digest"]),tuple((int(x[0]),tuple(x[1])) for x in p["shard_assignments"])) for i in range(int(g.parameters["placement_count"])))

def experiment_shard_plan_digest(g: NoetriumUnit) -> str:
    if not g.has_trait(EXPERIMENT_SHARD_PLAN_TRAIT): raise TypeError("expected experiment shard graph")
    return g.semantic_digest

def experiment_worker_scope_for_assignment(g: NoetriumUnit, assignment_digest: str) -> str:
    require_sha256(assignment_digest,"experiment shard lookup assignment_digest"); matches=tuple(x.worker_scope_id for x in experiment_shards(g) if assignment_digest in x.assignment_digests)
    if len(matches)!=1: raise KeyError("assignment has no unique experiment worker placement")
    return matches[0]

def assert_experiment_shard_complete(g: NoetriumUnit, compiled: NoetriumUnit) -> None:
    _assert_compiled_batch_authority(compiled); shards=experiment_shards(g); placements=experiment_batch_placements(g)
    if str(g.parameters["experiment_plan_digest"]) != study_plan_digest(experiment_compilation_plan(compiled)) or str(g.parameters["batch_plan_digest"]) != experiment_compilation_batch_digest(compiled): raise ValueError("experiment shard plan authority drifted")
    expected={study_assignment_digest(x) for x in study_plan_assignments(experiment_compilation_plan(compiled))}; actual=tuple(d for x in shards for d in x.assignment_digests)
    if set(actual)!=expected or len(actual)!=len(expected): raise ValueError("experiment shard plan does not exactly cover assignments")
    batches=experiment_compilation_batches(compiled)
    if len(placements)!=len(batches): raise ValueError("experiment shard plan batch count drifted")
    for x,y in zip(placements,batches,strict=True):
        if x.batch_id!=y.batch_id or x.batch_digest!=y.batch_digest or set(x.assignment_digests)!=set(y.assignment_digests): raise ValueError("experiment batch placement drifted")


def _assert_compiled_batch_authority(
    compiled: NoetriumUnit,
) -> None:
    expected_batch_plan_digest = canonical_digest(
        tuple(batch.batch_digest for batch in experiment_compilation_batches(compiled))
    )
    if experiment_compilation_batch_digest(compiled) != expected_batch_plan_digest:
        raise ValueError("compiled ExperimentProgram batch plan digest drifted")
    expected_assignments = {
        study_assignment_digest(row) for row in study_plan_assignments(experiment_compilation_plan(compiled))
    }
    scheduled = tuple(
        digest
        for batch in experiment_compilation_batches(compiled)
        for digest in batch.assignment_digests
    )
    if (
        len(scheduled) != len(set(scheduled))
        or set(scheduled) != expected_assignments
    ):
        raise ValueError(
            "compiled ExperimentProgram batches do not exactly cover assignments"
        )


def _best_heterogeneous_shard(
    shard_costs: list[int],
    capacities: tuple[int, ...],
    assignment_cost: int,
) -> int:
    """Exact argmin of (post-load ratio, current-load ratio, shard index).

    Cross multiplication preserves Fraction-exact ordering without allocating
    rational objects for every candidate on every assignment.
    """

    best = 0
    for index in range(1, len(shard_costs)):
        candidate_post = (shard_costs[index] + assignment_cost) * capacities[best]
        best_post = (shard_costs[best] + assignment_cost) * capacities[index]
        if candidate_post < best_post:
            best = index
            continue
        if candidate_post > best_post:
            continue
        candidate_current = shard_costs[index] * capacities[best]
        best_current = shard_costs[best] * capacities[index]
        if candidate_current < best_current:
            best = index
            continue
        if candidate_current == best_current and index < best:
            best = index
    return best


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
    compiled: NoetriumUnit,
    *,
    shard_count: int,
    assignment_cost_units: Mapping[str, int] | None = None,
    shard_capacity_units: tuple[int, ...] | None = None,
    worker_scope_ids: tuple[str, ...] | None = None,
) -> NoetriumUnit:
    """Compile deterministic worker placement without changing batch semantics.

    Assignments are globally placed with deterministic LPT balancing. Every
    authoritative ExperimentBatch is then projected through that fixed mapping.
    A server coordinator must dispatch batch_placements in the existing batch
    order; shards are routing destinations, not independent schedulers.

    Cost and worker-capacity hints are deployment metadata only. A supplied
    assignment mapping must exactly cover all authoritative assignments. Worker
    capacities are positive integer throughput units and must exactly match the
    requested shard count. They never change scientific batching or assignment
    identity; they only minimize projected deployment makespan.
    """

    if type(compiled) is not NoetriumUnit:
        raise TypeError(
            "experiment sharding requires NoetriumUnit"
        )
    require_study_execution_plan(experiment_compilation_plan(compiled))
    shard_count = _positive_int(shard_count, "experiment shard_count")
    if worker_scope_ids is None:
        scope_prefix = f"experiment-shard:{experiment_compilation_batch_digest(compiled)[:16]}"
        worker_scopes = tuple(
            f"{scope_prefix}:{index}" for index in range(shard_count)
        )
        worker_scope_kind = "generated-worker-scope-v1"
    else:
        if type(worker_scope_ids) is not tuple:
            raise TypeError("worker_scope_ids must be a tuple")
        if len(worker_scope_ids) != shard_count:
            raise ValueError(
                "worker_scope_ids must contain exactly shard_count entries"
            )
        if any(type(value) is not str or not value.strip() for value in worker_scope_ids):
            raise ValueError("worker_scope_ids must contain non-empty strings")
        if len(set(worker_scope_ids)) != len(worker_scope_ids):
            raise ValueError("worker_scope_ids must be unique")
        worker_scopes = tuple(value.strip() for value in worker_scope_ids)
        worker_scope_kind = "explicit-worker-scope-v1"

    if shard_capacity_units is None:
        capacities = tuple(1 for _ in range(shard_count))
        capacity_model_kind = "uniform-worker-capacity-v1"
    else:
        if type(shard_capacity_units) is not tuple:
            raise TypeError("shard_capacity_units must be a tuple")
        if len(shard_capacity_units) != shard_count:
            raise ValueError(
                "shard_capacity_units must contain exactly shard_count entries"
            )
        capacities = tuple(
            _positive_int(value, f"shard capacity for index {index}")
            for index, value in enumerate(shard_capacity_units)
        )
        capacity_model_kind = "explicit-integer-worker-capacity-v1"

    expected = {
        study_assignment_digest(row) for row in study_plan_assignments(experiment_compilation_plan(compiled))
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
            "worker_capacity_kind": capacity_model_kind,
            "shard_capacity_units": capacities,
            "worker_scope_kind": worker_scope_kind,
            "worker_scope_ids": worker_scopes,
        }
    )

    assignment_rows = sorted(
        study_plan_assignments(experiment_compilation_plan(compiled)),
        key=lambda row: (
            -costs[study_assignment_digest(row)],
            study_assignment_digest(row),
        ),
    )
    shard_rows: list[list[str]] = [[] for _ in range(shard_count)]
    shard_costs = [0 for _ in range(shard_count)]
    assignment_to_shard: dict[str, int] = {}
    uniform_capacity = len(set(capacities)) == 1
    load_heap = (
        [(0, index) for index in range(shard_count)]
        if uniform_capacity
        else None
    )
    if load_heap is not None:
        heapq.heapify(load_heap)

    for assignment in assignment_rows:
        digest = study_assignment_digest(assignment)
        assignment_cost = costs[digest]
        if load_heap is not None:
            current_load, target = heapq.heappop(load_heap)
            # Heap load is the canonical current cost for this shard. Keep the
            # mirrored list as the final projection source and assert drift-free.
            if current_load != shard_costs[target]:
                raise RuntimeError("experiment shard load heap drifted")
        else:
            target = _best_heterogeneous_shard(
                shard_costs, capacities, assignment_cost
            )
        shard_rows[target].append(digest)
        shard_costs[target] += assignment_cost
        assignment_to_shard[digest] = target
        if load_heap is not None:
            heapq.heappush(load_heap, (shard_costs[target], target))

    shards = tuple(
        ExperimentShard(
            shard_index=index,
            worker_scope_id=worker_scopes[index],
            assignment_digests=tuple(shard_rows[index]),
            estimated_cost_units=shard_costs[index],
            capacity_units=capacities[index],
        )
        for index in range(shard_count)
    )
    batch_placements = tuple(
        _batch_placement(
            batch,
            assignment_to_shard=assignment_to_shard,
            shard_count=shard_count,
        )
        for batch in experiment_compilation_batches(compiled)
    )
    result = experiment_shard_plan_graph(study_plan_digest(experiment_compilation_plan(compiled)), experiment_compilation_batch_digest(compiled), cost_model_digest, shards, batch_placements)
    assert_experiment_shard_complete(result, compiled)
    return result


__all__ = [
    "EXPERIMENT_SHARD_PLAN_TRAIT",
    "experiment_shard_plan_graph",
    "experiment_shards",
    "experiment_batch_placements",
    "experiment_shard_plan_digest",
    "experiment_worker_scope_for_assignment",
    "assert_experiment_shard_complete",
    "ExperimentBatchPlacement",
    "ExperimentShard",
    "compile_experiment_shard_plan",
]
