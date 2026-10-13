"""Automatic experiment sharding across a frozen qualified model replica set."""
from __future__ import annotations

from noetrium_platform.foundation.kernel.structure import structure_unit
from noetrium_platform.foundation.kernel.structure import NoetriumUnit


from collections.abc import Mapping
from dataclasses import dataclass, field

from noetrium_platform.research.execution.api import (
    ProjectModelBinding,
    ProjectModelBindingSet,
)
from noetrium_platform.research.execution.api import (
    QualifiedModelEndpointBinding,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.api import (
    compile_experiment_shard_plan, experiment_shards, experiment_shard_plan_digest,
)


@dataclass(frozen=True, slots=True)
class ModelReplicaWorker:
    """One exact qualified deployment admitted as an experiment worker."""

    worker_scope_id: str
    binding_digest: str
    deployment_id: str
    deployment_generation: str
    capacity_units: int
    worker_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.worker_scope_id.strip() or not self.deployment_id.strip():
            raise ValueError("model replica worker identity is required")
        require_sha256(self.binding_digest, "model replica worker binding_digest")
        require_sha256(
            self.deployment_generation,
            "model replica worker deployment_generation",
        )
        if type(self.capacity_units) is not int or self.capacity_units <= 0:
            raise ValueError("model replica worker capacity_units must be positive")
        object.__setattr__(
            self,
            "worker_digest",
            canonical_digest(
                {
                    "worker_scope_id": self.worker_scope_id,
                    "binding_digest": self.binding_digest,
                    "deployment_id": self.deployment_id,
                    "deployment_generation": self.deployment_generation,
                    "capacity_units": self.capacity_units,
                }
            ),
        )


MODEL_REPLICA_SHARD_PLAN_TRAIT = "model.replica-shard-plan"

def model_replica_shard_plan_graph(binding_set_digest: str, workers: tuple[ModelReplicaWorker,...], shard_plan: NoetriumUnit) -> NoetriumUnit:
    require_sha256(binding_set_digest,"model replica binding_set_digest")
    if not workers: raise ValueError("model replica shard plan requires workers")
    if len({x.worker_scope_id for x in workers})!=len(workers) or len({x.binding_digest for x in workers})!=len(workers): raise ValueError("model replica workers must be unique")
    shards=experiment_shards(shard_plan)
    if tuple(x.worker_scope_id for x in workers)!=tuple(x.worker_scope_id for x in shards) or tuple(x.capacity_units for x in workers)!=tuple(x.capacity_units for x in shards): raise ValueError("model replica workers and experiment shards drifted")
    members=tuple(structure_unit(f"worker:{i}",traits=("model.replica-worker",),parameters={"worker_scope_id":x.worker_scope_id,"binding_digest":x.binding_digest,"deployment_id":x.deployment_id,"deployment_generation":x.deployment_generation,"capacity_units":x.capacity_units}) for i,x in enumerate(workers))+(structure_unit("shard-plan",traits=("model.replica-placement",),members=(shard_plan,)),)
    return structure_unit("model-replica-plan:"+canonical_digest((binding_set_digest,tuple(x.worker_digest for x in workers),experiment_shard_plan_digest(shard_plan)))[:20],traits=(MODEL_REPLICA_SHARD_PLAN_TRAIT,),parameters={"binding_set_digest":binding_set_digest,"worker_count":len(workers)},members=members)

def model_replica_workers(g:NoetriumUnit)->tuple[ModelReplicaWorker,...]:
    if not g.has_trait(MODEL_REPLICA_SHARD_PLAN_TRAIT): raise TypeError("expected model replica shard graph")
    return tuple(ModelReplicaWorker(str((p:=g.member(f"worker:{i}").parameters)["worker_scope_id"]),str(p["binding_digest"]),str(p["deployment_id"]),str(p["deployment_generation"]),int(p["capacity_units"])) for i in range(int(g.parameters["worker_count"])))
def model_replica_experiment_shards(g:NoetriumUnit)->NoetriumUnit:
    if not g.has_trait(MODEL_REPLICA_SHARD_PLAN_TRAIT): raise TypeError("expected model replica shard graph")
    return g.member("shard-plan").members[0]


def _replica_equivalence_key(binding: ProjectModelBinding) -> tuple[object, ...]:
    return (
        binding.requirement_digest,
        binding.provider_id,
        binding.role,
        binding.model,
        binding.model_stack_digest,
        binding.prompt_generation_id,
        binding.prompt_id,
        binding.prompt_digest,
        binding.capabilities,
        binding.capability_id,
        binding.input_schema_id,
        binding.output_schema_id,
    )


def _assert_replica_set(binding_set: ProjectModelBindingSet) -> None:
    if not isinstance(binding_set, ProjectModelBindingSet):
        raise TypeError("replica sharding requires ProjectModelBindingSet")
    keys = {_replica_equivalence_key(binding) for binding in binding_set.bindings}
    if len(keys) != 1:
        raise ValueError(
            "model replica sharding requires scientifically equivalent bindings"
        )


def qualified_replica_capacity_units(
    binding_set: ProjectModelBindingSet,
    qualified_bindings: tuple[QualifiedModelEndpointBinding, ...],
) -> dict[str, int]:
    """Project qualification concurrency into frozen project-binding capacity."""

    _assert_replica_set(binding_set)
    if type(qualified_bindings) is not tuple or any(
        not isinstance(row, QualifiedModelEndpointBinding)
        for row in qualified_bindings
    ):
        raise TypeError(
            "qualified replica capacities require QualifiedModelEndpointBinding tuple"
        )
    qualified_by_deployment = {
        (row.deployment_id, row.deployment_generation): row
        for row in qualified_bindings
    }
    if len(qualified_by_deployment) != len(qualified_bindings):
        raise ValueError("qualified replica deployment identities must be unique")
    result: dict[str, int] = {}
    for binding in binding_set.bindings:
        key = (binding.deployment_id, binding.deployment_generation)
        try:
            qualified = qualified_by_deployment[key]
        except KeyError as exc:
            raise ValueError(
                "frozen model binding has no qualified replica capacity"
            ) from exc
        if (
            qualified.role != binding.role
            or qualified.model != binding.model
            or qualified.model_stack_digest != binding.model_stack_digest
            or qualified.prompt_generation != binding.prompt_generation_id
        ):
            raise ValueError("qualified replica identity drifted from project binding")
        result[binding.digest()] = qualified.max_admitted_concurrency
    if len(result) != len(binding_set.bindings):
        raise ValueError("qualified replica capacities do not cover binding set")
    return result


def compile_model_replica_shard_plan(
    compiled: NoetriumUnit,
    *,
    binding_set: ProjectModelBindingSet,
    capacity_units: Mapping[str, int],
    assignment_cost_units: Mapping[str, int] | None = None,
) -> NoetriumUnit:
    """Automatically spread authoritative assignments across exact replicas.

    The binding set is already frozen scientific authority. This function only
    projects deployment capacity into worker placement; it never changes model,
    prompt, treatment, benchmark, batching, or assignment identity.
    """

    if not isinstance(compiled, NoetriumUnit):
        raise TypeError(
            "model replica sharding requires NoetriumUnit"
        )
    _assert_replica_set(binding_set)
    if not isinstance(capacity_units, Mapping):
        raise TypeError("model replica capacity_units must be a mapping")
    bindings = tuple(sorted(
        binding_set.bindings,
        key=lambda row: (row.deployment_id, row.deployment_generation, row.digest()),
    ))
    binding_digests = tuple(row.digest() for row in bindings)
    if set(capacity_units) != set(binding_digests):
        raise ValueError(
            "model replica capacities must exactly cover frozen binding set"
        )

    workers = tuple(
        ModelReplicaWorker(
            worker_scope_id=(
                f"model-replica:{binding.provider_id}:"
                f"{binding.deployment_id}:{binding.deployment_generation[:16]}"
            ),
            binding_digest=binding.digest(),
            deployment_id=binding.deployment_id,
            deployment_generation=binding.deployment_generation,
            capacity_units=capacity_units[binding.digest()],
        )
        for binding in bindings
    )
    shard_plan = compile_experiment_shard_plan(
        compiled,
        shard_count=len(workers),
        assignment_cost_units=assignment_cost_units,
        shard_capacity_units=tuple(row.capacity_units for row in workers),
        worker_scope_ids=tuple(row.worker_scope_id for row in workers),
    )
    return model_replica_shard_plan_graph(binding_set.binding_set_digest, workers, shard_plan)


__all__ = [
    "MODEL_REPLICA_SHARD_PLAN_TRAIT",
    "model_replica_shard_plan_graph",
    "model_replica_workers",
    "model_replica_experiment_shards",
    "ModelReplicaWorker",
    "compile_model_replica_shard_plan",
    "qualified_replica_capacity_units",
]
