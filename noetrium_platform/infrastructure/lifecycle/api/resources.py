"""Runtime-facing resource contracts for capability systems.

Resource remains the authority. Runtime projects the subset of resource contracts
needed to materialize model and environment processes without exposing Resource
internals to Capability systems.
"""

from noetrium_platform.foundation.api import (
    ComputeAllocation,
    ComputeAllocationBatch,
    ComputeAllocationRequest,
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

__all__ = [
    "ComputeAllocation",
    "ComputeAllocationBatch",
    "ComputeAllocationRequest",
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
]
