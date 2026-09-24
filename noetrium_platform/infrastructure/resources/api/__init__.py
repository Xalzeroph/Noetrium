from noetrium_platform.infrastructure.resources.directory.api import (
    DirectoryLayoutPort,
    ManagedDirectoryKind,
)

__all__ = ["DirectoryLayoutPort", "ManagedDirectoryKind"]

from noetrium_platform.infrastructure.resources.allocation.api import (
    EndpointAllocation,
    EndpointCandidatePortSourcePort,
    EndpointAllocationPort,
    EndpointAllocationRequest,
    EndpointAllocationState,
    EndpointBindingProof,
    EndpointLeaseGuardFactoryPort,
    EndpointLeaseGuardPort,
)
from noetrium_platform.infrastructure.resources.container.api import (
    DEFAULT_DOCKER_CONTAINER_LEASE_POLICY,
    DockerContainerLeaseGuardFactoryPort,
    DockerContainerLeaseGuardPort,
    DockerContainerLeasePolicy,
    DockerContainerObservation,
    DockerManagedContainerPort,
    ManagedDockerContainerLease,
)
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeAllocation,
    ComputeLeaseGuardFactoryPort,
    ComputeLeaseGuardPort,
    ComputePlacementUnavailable,
    ComputeRequirement,
    ComputeSchedulerPort,
    GpuDeviceStatus,
    GpuProcessStatus,
    GpuRuntimeObserverPort,
    GpuRuntimeSnapshot,
    GpuSharingMode,
)
from noetrium_platform.infrastructure.resources.lease.api import ResourceOwnership
from noetrium_platform.infrastructure.resources.resolution.api import (
    HierarchicalResourceResolver,
    ResolutionPolicy,
    ScopedValue,
)

_RESOURCE_PARENT_EXTRA_EXPORTS = (
    "ComputeAllocation",
    "DEFAULT_DOCKER_CONTAINER_LEASE_POLICY",
    "DockerContainerLeaseGuardFactoryPort",
    "DockerContainerLeaseGuardPort",
    "DockerContainerLeasePolicy",
    "DockerContainerObservation",
    "DockerManagedContainerPort",
    "ManagedDockerContainerLease",
    "ComputeLeaseGuardFactoryPort",
    "ComputeLeaseGuardPort",
    "ComputePlacementUnavailable",
    "ComputeRequirement",
    "ComputeSchedulerPort",
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
    "GpuSharingMode",
    "HierarchicalResourceResolver",
    "ResolutionPolicy",
    "ResourceOwnership",
    "ScopedValue",
)

__all__ = tuple(__all__) + _RESOURCE_PARENT_EXTRA_EXPORTS
