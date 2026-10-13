from __future__ import annotations

from resource_test_support import build_test_platform_meta

from noetrium_platform.composition.platform_meta import build_platform_meta
from noetrium_platform.evidence.data.dataset.api import DatasetIdentity, DatasetQuery, DatasetVersion
from noetrium_platform.foundation.governance.architecture.system_graphs import (
    declared_subsystem_graph,
    declared_system_graph,
)
from noetrium_platform.infrastructure.resources.authority import resource_claim
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeGPU,
    ComputeHost,
    ComputeRequirement,
)
from noetrium_platform.infrastructure.resources.compute.placement import (
    compute_capacity,
    compute_claim_candidates,
    compute_placement_from_claim,
)
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE, NoetriumUnit, ScopeKind
from tests.resource_compute_support import idle_gpu_runtime_observer


def test_platform_meta_composes_one_resource_authority(tmp_path) -> None:
    meta = build_test_platform_meta(tmp_path / "meta")
    generation = meta.resource_authority.ensure_generation("storage:pool-a")
    claim_request = resource_claim(
        "storage-claim:a",
        "storage:pool-a",
        "paper-a",
        generation.generation,
        attributes={"kind": "storage"},
    )
    claim = meta.resource_authority.acquire_claim(claim_request)
    lease = meta.resource_authority.acquire_ttl_lease(
        lease_id="lease-a",
        resource_key="storage:pool-a",
        holder_key="paper-a",
        ttl_seconds=120.0,
        metadata={"purpose": "paper artifacts"},
    )
    snapshot = meta.resource_authority.snapshot()
    assert snapshot.current_claims_for("storage:pool-a") == (claim,)
    assert meta.resource_authority.active_leases("storage:pool-a") == (lease,)
    assert not hasattr(meta, "resource_ownership")
    assert not hasattr(meta, "resource_leases")


def test_platform_meta_compute_facts_feed_pure_placement_and_authority_admission(tmp_path) -> None:
    meta = build_test_platform_meta(
        tmp_path / "meta",
        gpu_runtime_observer=idle_gpu_runtime_observer("0", "1"),
    )
    host = ComputeHost(
        "gpu01",
        PLATFORM_SCOPE,
        64,
        512 * 1024**3,
        gpus=(
            ComputeGPU("0", 80 * 1024**3, "H100"),
            ComputeGPU("1", 80 * 1024**3, "H100"),
        ),
    )
    meta.compute_inventory.register_host(host)
    meta.resource_authority.declare_capacity(compute_capacity((host,)))
    resource_key = "compute:model-test"
    generation = meta.resource_authority.ensure_generation(resource_key).generation
    requirement = ComputeRequirement(
        cpu_cores=8,
        memory_bytes=32 * 1024**3,
        gpu_count=1,
        minimum_gpu_memory_bytes=70 * 1024**3,
    )
    candidates = compute_claim_candidates(
        resource_key=resource_key,
        holder_key="model-test",
        generation=generation,
        consumer_resource_key="model-service:test",
        requirement=requirement,
        hosts=meta.compute_inventory.list_hosts(scope=PLATFORM_SCOPE),
        authority=meta.resource_authority.snapshot(),
        placement_scope=PLATFORM_SCOPE,
        gpu_runtime=meta.gpu_runtime_observer.snapshot(),
    )
    claim = meta.resource_authority.admit_first(candidates)
    placement = compute_placement_from_claim(claim)
    assert placement.host_id == "gpu01"
    assert len(placement.gpu_ids) == 1
    assert not hasattr(meta, "compute_scheduler")


def test_dataset_versions_are_scoped_portable_and_immutable_by_identity(tmp_path) -> None:
    meta = build_test_platform_meta(tmp_path / "meta")
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
    assert any(
        row.source == "execution" and row.target == "execution/operation"
        for row in subsystems
    )
    assert any(
        row.source == "governance" and row.target == "governance/system_registry"
        for row in subsystems
    )
    assert any(
        row.source == "environment" and row.target == "environment/minecraft"
        for row in subsystems
    )
