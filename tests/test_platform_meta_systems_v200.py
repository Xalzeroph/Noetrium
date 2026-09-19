from __future__ import annotations

from noetrium_platform.composition.platform_meta import build_in_memory_platform_meta
from noetrium_platform.evidence.data.dataset.api import DatasetIdentity, DatasetQuery, DatasetVersion
from noetrium_platform.foundation.governance.architecture.system_graphs import declared_subsystem_graph, declared_system_graph
from noetrium_platform.infrastructure.resources.compute.api import ComputeGPU, ComputeHost, ComputeRequirement
from noetrium_platform.infrastructure.resources.lease.api import ResourceIdentity, ResourceKind, ResourceLease, ResourceOwner
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE, ScopeIdentity, ScopeKind


def test_platform_meta_composes_independent_authorities() -> None:
    meta = build_in_memory_platform_meta()
    project = ScopeIdentity(ScopeKind.PROJECT, "paper-a")
    workspace = ScopeIdentity(ScopeKind.WORKSPACE, "ws")
    program = ScopeIdentity(ScopeKind.PROGRAM, "prog")
    meta.scopes.register(workspace, PLATFORM_SCOPE)
    meta.scopes.register(program, workspace)
    meta.scopes.register(project, program)

    resource = ResourceIdentity(ResourceKind.STORAGE, "pool-a")
    meta.resource_ownership.register_owner(ResourceOwner(resource, project))
    meta.resource_leases.acquire(ResourceLease("lease-a", resource, project, "paper artifacts"))
    assert meta.resource_ownership.owner(resource).scope == project
    assert meta.resource_leases.active_for(resource)[0].lease_id == "lease-a"


def test_compute_scheduler_allocates_matching_gpu_without_embedding_host_policy_in_runs() -> None:
    meta = build_in_memory_platform_meta()
    meta.compute_inventory.register_host(ComputeHost(
        "gpu01", PLATFORM_SCOPE, 64, 512 * 1024**3,
        gpus=(ComputeGPU("0", 80 * 1024**3, "H100"), ComputeGPU("1", 80 * 1024**3, "H100")),
    ))
    requirement = ComputeRequirement(cpu_cores=8, memory_bytes=32 * 1024**3, gpu_count=1, minimum_gpu_memory_bytes=70 * 1024**3)
    allocation = meta.compute_scheduler.allocate("alloc-1", PLATFORM_SCOPE, requirement)
    assert allocation.host_id == "gpu01"
    assert len(allocation.gpu_ids) == 1


def test_dataset_versions_are_scoped_portable_and_immutable_by_identity() -> None:
    meta = build_in_memory_platform_meta()
    row = DatasetVersion(
        DatasetIdentity("benchmark", "v1"),
        PLATFORM_SCOPE,
        "d" * 64,
        parent_versions=(DatasetIdentity("benchmark-source", "v3"),),
    )
    meta.datasets.register(row)
    assert meta.datasets.get(row.identity) == row
    assert meta.datasets.query(DatasetQuery(dataset_id="benchmark")) == (row,)
    assert not hasattr(row, "location")


def test_architecture_exposes_system_and_subsystem_graphs() -> None:
    systems = declared_system_graph()
    subsystems = declared_subsystem_graph()
    assert any(row.source == "model" and row.target == "resource" for row in systems)
    assert any(row.target == "resource/compute" for row in subsystems)
    assert any(row.target == "data/dataset" for row in subsystems)
