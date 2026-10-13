from .component import (
    LifecycleEvidence,
    LifecyclePhase,
)

__all__ = [
    "LifecycleEvidence",
    "LifecyclePhase",
]

# Parent-facing Runtime contracts and sanctioned factories.
from noetrium_platform.foundation.kernel.event_store import FileCausalEventStore
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
    ServiceQuiescenceOutcome,
    ServiceReadinessProbePort,
    ServiceRuntimeFactoryPort,
    ServiceReadyObservation,
    ServiceReconcileObservation,
    ServiceStartOutcome,
    ServiceStopOutcome,
)
from noetrium_platform.infrastructure.lifecycle.toolchain.api import RuntimeToolchainError, parse_java_major

_PARENT_FACADE_EXPORTS = (
    "FileCausalEventStore",
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
    "ServiceQuiescenceOutcome",
    "ServiceReadyObservation",
    "ServiceReconcileObservation",
    "ServiceStartOutcome",
    "ServiceStopOutcome",
    "parse_java_major",
)

__all__ = tuple(__all__) + _PARENT_FACADE_EXPORTS

from .resources import (
    ComputePlacementUnavailable,
    ComputeRequirement,
    DirectoryLayoutPort,
    EndpointCandidatePortSourcePort,
    GpuDeviceStatus,
    GpuProcessStatus,
    GpuRuntimeObserverPort,
    GpuRuntimeSnapshot,
    HierarchicalResourceResolver,
    ManagedDirectoryKind,
    ResolutionPolicy,
    ScopedValue,
)

_RUNTIME_RESOURCE_EXPORTS = (
    "ComputePlacementUnavailable",
    "ComputeRequirement",
    "DirectoryLayoutPort",
    "EndpointCandidatePortSourcePort",
    "GpuDeviceStatus",
    "GpuProcessStatus",
    "GpuRuntimeObserverPort",
    "GpuRuntimeSnapshot",
    "HierarchicalResourceResolver",
    "ManagedDirectoryKind",
    "ResolutionPolicy",
    "ScopedValue",
)

__all__ = tuple(__all__) + _RUNTIME_RESOURCE_EXPORTS
