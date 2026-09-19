"""Composition roots for binding MC contracts to concrete platform seams."""

from .participant_runtime import MinecraftParticipantRuntimeAdapter, compose_minecraft_participant_endpoint
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
from .diagnostics import (
    MinecraftDiagnosticContext,
    MinecraftFailureMaterializer,
    StructuredMinecraftDiagnostics,
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
from .agent_io import MinecraftAgentActionExecutor, MinecraftAgentObservationPort

__all__ = [
    "MinecraftParticipantRuntimeAdapter",
    "compose_minecraft_participant_endpoint",
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
    "MinecraftDiagnosticContext",
    "MinecraftFailureMaterializer",
    "StructuredMinecraftDiagnostics",
    "LocalMinecraftExperimentHostFactory",
    "MinecraftExperimentHost",
    "MinecraftExperimentHostInputs",
    "MinecraftSourceServerPort",
    "MinecraftServerArtifactAssembly",
    "compose_official_minecraft_server_artifacts",
    "MinecraftAgentActionExecutor",
    "MinecraftAgentObservationPort",
]
