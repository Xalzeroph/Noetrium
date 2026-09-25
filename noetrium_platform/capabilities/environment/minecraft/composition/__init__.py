"""Composition roots for binding MC contracts to concrete platform seams."""

from .environment import MinecraftEnvironmentAssembly, compose_minecraft_environment
from .assignment_isolation import (
    MinecraftBranchAssignmentIsolation,
    MinecraftBranchAssignmentIsolationFactory,
)
from .branch_runtime import (
    MinecraftBranchCheckpointFactoryPort,
    MinecraftBranchEnvironmentFactoryPort,
    MinecraftBranchRuntimeBinding,
    MinecraftBranchRuntimeError,
    MinecraftBranchRuntimeFactory,
)
from .server_service import (
    MinecraftServerServiceController,
    MinecraftServerServiceError,
    MinecraftServerServiceFactory,
    MinecraftServerServiceFactoryConfig,
    MinecraftServerReadinessProbe,
    MinecraftTcpReadinessProbe,
    build_server_service_contract,
    compose_minecraft_server_service_runtime,
)
from .experiment_host import (
    LocalMinecraftExperimentHostFactory,
    MinecraftExperimentHost,
    MinecraftExperimentHostInputs,
    MinecraftSourceServerPort,
)
from .server_artifact import (
    MinecraftServerArtifactAssembly,
    compose_official_minecraft_server_artifacts,
)

__all__ = [
    "MinecraftEnvironmentAssembly",
    "MinecraftBranchCheckpointFactoryPort",
    "MinecraftBranchEnvironmentFactoryPort",
    "MinecraftBranchRuntimeBinding",
    "MinecraftBranchRuntimeError",
    "MinecraftBranchRuntimeFactory",
    "MinecraftBranchAssignmentIsolation",
    "MinecraftBranchAssignmentIsolationFactory",
    "MinecraftServerServiceController",
    "MinecraftServerServiceError",
    "MinecraftServerServiceFactory",
    "MinecraftServerServiceFactoryConfig",
    "MinecraftServerReadinessProbe",
    "MinecraftTcpReadinessProbe",
    "build_server_service_contract",
    "compose_minecraft_server_service_runtime",
    "compose_minecraft_environment",
    "LocalMinecraftExperimentHostFactory",
    "MinecraftExperimentHost",
    "MinecraftExperimentHostInputs",
    "MinecraftSourceServerPort",
    "MinecraftServerArtifactAssembly",
    "compose_official_minecraft_server_artifacts",
]
