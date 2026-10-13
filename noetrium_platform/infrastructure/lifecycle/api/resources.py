"""Runtime-facing resource contracts for capability systems.

Resource remains the authority. Runtime projects the subset of resource contracts
needed to materialize model and environment processes without exposing Resource
internals to Capability systems.
"""

from noetrium_platform.foundation.api import (
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

__all__ = [
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
]
