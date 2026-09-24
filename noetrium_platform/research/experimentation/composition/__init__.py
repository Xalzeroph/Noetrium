"""Experiment composition is Program-driven.

Concrete applications bind a frozen CompiledExperimentProgram to an execution
adapter, aggregation implementation and optional TaskGroupPort. No independent
ExperimentRunner facade owns another execution loop.
"""

from noetrium_platform.research.experimentation.api import (
    CompiledExperimentProgram,
    ExperimentProgramBinding,
)

__all__ = ["CompiledExperimentProgram", "ExperimentProgramBinding"]

from .model_replica_sharding import (
    ModelReplicaShardPlan,
    ModelReplicaWorker,
    compile_model_replica_shard_plan,
    qualified_replica_capacity_units,
)

__all__ += [
    "ModelReplicaShardPlan",
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

from .binding_authority import (
    CanonicalResearchBindingAuthority,
    ResearchCapabilityBindingResolverPort,
    ResearchModelRoleBindingResolverPort,
    ResearchParticipantBindingResolverPort,
    ResearchProjectManifestResolverPort,
)

__all__ += [
    "CanonicalResearchBindingAuthority",
    "ResearchCapabilityBindingResolverPort",
    "ResearchModelRoleBindingResolverPort",
    "ResearchParticipantBindingResolverPort",
    "ResearchProjectManifestResolverPort",
]
