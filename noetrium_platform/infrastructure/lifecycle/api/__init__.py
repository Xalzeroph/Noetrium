from .component import (
    LifecycleComponent,
    LifecycleEvidence,
    LifecyclePhase,
    LifecycleSpec,
)

__all__ = [
    "LifecycleComponent",
    "LifecycleEvidence",
    "LifecyclePhase",
    "LifecycleSpec",
]

# Parent-facing Runtime contracts and sanctioned factories.
from noetrium_platform.infrastructure.lifecycle.host.api import OperatingSystemRoute
from noetrium_platform.infrastructure.lifecycle.process.api import ProcessSupervisorPort
from noetrium_platform.infrastructure.lifecycle.process.api import (
    LocalCommandRunnerPort,
    LocalCommandStartError,
    LocalCommandTimeoutError,
)
from noetrium_platform.infrastructure.lifecycle.python.api import (
    EnvironmentCommandResult,
    PythonEnvironmentExecutionPort,
    PythonEnvironmentLookupPort,
    PythonPackageManagementPort,
)
from noetrium_platform.infrastructure.lifecycle.service.api import (
    ExactServiceRuntimePort,
    MaterializedServiceEnvironment,
    ServiceContractDrift,
    ServiceEnvironmentPort,
    ServiceHeartbeat,
    ServiceLaunchContract,
    ServiceLaunchPreflightPort,
    ServiceLaunchPreflightReport,
    ServiceProcessIdentity,
    ServiceProcessLivenessPort,
    ServiceReadinessProbePort,
    ServiceRuntimeFactoryPort,
    ServiceReadyObservation,
    ServiceReconcileObservation,
    ServiceStartOutcome,
    ServiceStopOutcome,
)
from noetrium_platform.infrastructure.lifecycle.toolchain.api import RuntimeToolchainError, parse_java_major

_PARENT_FACADE_EXPORTS = (
    "ServiceLaunchPreflightReport",
    "ServiceEnvironmentPort",
    "ServiceRuntimeFactoryPort",
    "ServiceReadinessProbePort",
    "ServiceProcessLivenessPort",
    "MaterializedServiceEnvironment",
    "ProcessSupervisorPort",
    "EnvironmentCommandResult",
    "ExactServiceRuntimePort",
    "LocalCommandRunnerPort",
    "LocalCommandStartError",
    "LocalCommandTimeoutError",
    "OperatingSystemRoute",
    "PythonEnvironmentExecutionPort",
    "PythonEnvironmentLookupPort",
    "PythonPackageManagementPort",
    "RuntimeToolchainError",
    "ServiceContractDrift",
    "ServiceHeartbeat",
    "ServiceLaunchContract",
    "ServiceLaunchPreflightPort",
    "ServiceProcessIdentity",
    "ServiceReadyObservation",
    "ServiceReconcileObservation",
    "ServiceStartOutcome",
    "ServiceStopOutcome",
    "parse_java_major",
)

__all__ = tuple(__all__) + _PARENT_FACADE_EXPORTS

from .resources import (
    ComputeAllocation,
    ComputeBindingProof,
    ComputeLeaseGuardFactoryPort,
    ComputePlacementUnavailable,
    ComputeRequirement,
    ComputeSchedulerPort,
    DirectoryLayoutPort,
    EndpointAllocation,
    EndpointCandidatePortSourcePort,
    EndpointAllocationPort,
    EndpointAllocationRequest,
    EndpointAllocationState,
    EndpointBindingProof,
    EndpointLeaseGuardFactoryPort,
    EndpointLeaseGuardPort,
    GpuDeviceStatus,
    GpuProcessStatus,
    GpuRuntimeObserverPort,
    GpuRuntimeSnapshot,
    HierarchicalResourceResolver,
    ManagedDirectoryKind,
    ResolutionPolicy,
    ResourceOwnership,
    ScopedValue,
)

_RUNTIME_RESOURCE_EXPORTS = (
    "ComputeAllocation",
    "ComputeBindingProof",
    "ComputeLeaseGuardFactoryPort",
    "ComputePlacementUnavailable",
    "ComputeRequirement",
    "ComputeSchedulerPort",
    "DirectoryLayoutPort",
    "EndpointAllocation",
    "EndpointCandidatePortSourcePort",
    "EndpointAllocationPort",
    "EndpointAllocationRequest",
    "EndpointAllocationState",
    "EndpointBindingProof",
    "EndpointLeaseGuardFactoryPort",
    "EndpointLeaseGuardPort",
    "GpuDeviceStatus",
    "GpuProcessStatus",
    "GpuRuntimeObserverPort",
    "GpuRuntimeSnapshot",
    "HierarchicalResourceResolver",
    "ManagedDirectoryKind",
    "ResolutionPolicy",
    "ResourceOwnership",
    "ScopedValue",
)

__all__ = tuple(__all__) + _RUNTIME_RESOURCE_EXPORTS
