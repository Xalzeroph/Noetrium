"""Experiment composition is Program-driven.

Concrete applications bind a frozen experiment compilation graph to an execution
adapter, aggregation implementation and optional TaskGroupPort. No independent
ExperimentRunner facade owns another execution loop.
"""

from noetrium_platform.research.experimentation.api import (
    ExperimentProgramBinding,
)

__all__ = ["ExperimentProgramBinding"]

from .model_replica_sharding import (
    MODEL_REPLICA_SHARD_PLAN_TRAIT, model_replica_shard_plan_graph, model_replica_workers, model_replica_experiment_shards,
    ModelReplicaWorker,
    compile_model_replica_shard_plan,
    qualified_replica_capacity_units,
)

__all__ += [
    "MODEL_REPLICA_SHARD_PLAN_TRAIT", "model_replica_shard_plan_graph", "model_replica_workers", "model_replica_experiment_shards",
    "ModelReplicaWorker",
    "compile_model_replica_shard_plan",
    "qualified_replica_capacity_units",
]

from noetrium_platform.research.experimentation.lifecycle.composition import (
    bind_paired_evaluation_host,
)
from noetrium_platform.research.experimentation.workload.composition import (
    bind_method_workload,
)

__all__ += [
    "bind_method_workload",
    "bind_paired_evaluation_host",
]
