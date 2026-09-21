"""Automatic experiment sharding across a frozen qualified model replica set."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from noetrium_platform.capabilities.model.api import (
    ProjectModelBinding,
    ProjectModelBindingSet,
)
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    QualifiedModelEndpointBinding,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.api import (
    CompiledExperimentProgram,
    CompiledExperimentShardPlan,
    compile_experiment_shard_plan,
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


@dataclass(frozen=True, slots=True)
class ModelReplicaShardPlan:
    """Capacity-aware shard plan tied to one frozen model binding set."""

    binding_set_digest: str
    workers: tuple[ModelReplicaWorker, ...]
    shard_plan: CompiledExperimentShardPlan
    plan_digest: str = field(init=False)

    def __post_init__(self) -> None:
        require_sha256(self.binding_set_digest, "model replica binding_set_digest")
        if not self.workers:
            raise ValueError("model replica shard plan requires workers")
        if len({row.worker_scope_id for row in self.workers}) != len(self.workers):
            raise ValueError("model replica worker scopes must be unique")
        if len({row.binding_digest for row in self.workers}) != len(self.workers):
            raise ValueError("model replica worker bindings must be unique")
        if tuple(row.worker_scope_id for row in self.workers) != tuple(
            shard.worker_scope_id for shard in self.shard_plan.shards
        ):
            raise ValueError("model replica workers and experiment shards drifted")
        if tuple(row.capacity_units for row in self.workers) != tuple(
            shard.capacity_units for shard in self.shard_plan.shards
        ):
            raise ValueError("model replica worker capacity and shard capacity drifted")
        object.__setattr__(
            self,
            "plan_digest",
            canonical_digest(
                {
                    "binding_set_digest": self.binding_set_digest,
                    "worker_digests": tuple(row.worker_digest for row in self.workers),
                    "shard_plan_digest": self.shard_plan.shard_plan_digest,
                }
            ),
        )


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
    compiled: CompiledExperimentProgram,
    *,
    binding_set: ProjectModelBindingSet,
    capacity_units: Mapping[str, int],
    assignment_cost_units: Mapping[str, int] | None = None,
) -> ModelReplicaShardPlan:
    """Automatically spread authoritative assignments across exact replicas.

    The binding set is already frozen scientific authority. This function only
    projects deployment capacity into worker placement; it never changes model,
    prompt, treatment, benchmark, batching, or assignment identity.
    """

    if not isinstance(compiled, CompiledExperimentProgram):
        raise TypeError(
            "model replica sharding requires CompiledExperimentProgram"
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
    return ModelReplicaShardPlan(
        binding_set_digest=binding_set.binding_set_digest,
        workers=workers,
        shard_plan=shard_plan,
    )


__all__ = [
    "ModelReplicaShardPlan",
    "ModelReplicaWorker",
    "compile_model_replica_shard_plan",
    "qualified_replica_capacity_units",
]
