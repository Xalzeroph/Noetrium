from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from noetrium_platform.foundation.scope.api import ScopeKind, scope_unit
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.infrastructure.resources.authority import (
    AuthoritySnapshot,
    ResourceClaimConflict,
    UniversalResourceAuthority,
)
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeGPU,
    ComputeHost,
    ComputePlacementUnavailable,
    ComputeRequirement,
    GpuDeviceStatus,
    GpuRuntimeSnapshot,
)
from noetrium_platform.infrastructure.resources.compute.placement import (
    compute_capacity,
    compute_claim_candidates,
    compute_placement_from_claim,
)
from tests.resource_compute_support import TestComputeInventory


def _scope(name: str) -> NoetriumUnit:
    return scope_unit(ScopeKind.PROJECT, name)


def test_compute_candidates_never_cross_requested_scope() -> None:
    first = _scope("first")
    second = _scope("second")
    inventory = TestComputeInventory()
    inventory.register_host(ComputeHost("a-first", first, 8, 1024))
    inventory.register_host(ComputeHost("b-second", second, 8, 1024))
    claims = compute_claim_candidates(
        resource_key="compute:second",
        holder_key="second",
        generation=1,
        consumer_resource_key="service:second",
        requirement=ComputeRequirement(cpu_cores=1, memory_bytes=1),
        hosts=inventory.list_hosts(),
        authority=AuthoritySnapshot((), (), (), (), ()),
        placement_scope=second,
        owner_scope=second,
        scope_generation=1,
        scope_lease_id=None,
    )
    assert tuple(compute_placement_from_claim(row).host_id for row in claims) == (
        "b-second",
    )


def test_compute_candidate_projection_is_read_only() -> None:
    scope = _scope("read-only")
    host = ComputeHost("host", scope, 4, 4096)
    snapshot = AuthoritySnapshot((), (), (), (), ())
    before = snapshot
    claims = compute_claim_candidates(
        resource_key="compute:a",
        holder_key="a",
        generation=1,
        consumer_resource_key="service:a",
        requirement=ComputeRequirement(cpu_cores=2, memory_bytes=1024),
        hosts=(host,),
        authority=snapshot,
        placement_scope=scope,
        owner_scope=scope,
        scope_generation=1,
        scope_lease_id=None,
    )
    assert len(claims) == 1
    assert snapshot == before


def test_compute_admission_is_linearizable_under_thread_contention(tmp_path) -> None:
    scope = _scope("shared")
    host = ComputeHost("host", scope, 1, 1)
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    authority.ensure_scope_generation(scope)
    authority.declare_capacity(compute_capacity((host,)))

    def acquire(index: int):
        resource_key = f"compute:{index}"
        generation = authority.ensure_generation(resource_key).generation
        try:
            candidates = compute_claim_candidates(
                resource_key=resource_key,
                holder_key=f"holder:{index}",
                generation=generation,
                consumer_resource_key=f"service:{index}",
                requirement=ComputeRequirement(cpu_cores=1, memory_bytes=1),
                hosts=(host,),
                authority=authority.snapshot(),
                placement_scope=scope,
                owner_scope=scope,
                scope_generation=1,
                scope_lease_id=None,
            )
            return authority.admit_first(candidates)
        except (ResourceClaimConflict, ComputePlacementUnavailable):
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = tuple(pool.map(acquire, range(2)))
    assert sum(row is not None for row in rows) == 1
    assert len(authority.snapshot().claims) == 1


def test_multi_gpu_equivalent_quality_prefers_single_numa_domain() -> None:
    scope = _scope("topology")
    # Lexical GPU ids alone would choose GPU-a + GPU-b and cross NUMA domains.
    # Topology-aware tie-breaking must preserve the same runtime quality while
    # choosing the single-domain pair GPU-a + GPU-c.
    host = ComputeHost(
        "host",
        scope,
        32,
        128 << 30,
        (
            ComputeGPU("GPU-a", 24 << 30, labels=(("numa_node", "0"),)),
            ComputeGPU("GPU-b", 24 << 30, labels=(("numa_node", "1"),)),
            ComputeGPU("GPU-c", 24 << 30, labels=(("numa_node", "0"),)),
            ComputeGPU("GPU-d", 24 << 30, labels=(("numa_node", "1"),)),
        ),
    )
    runtime = GpuRuntimeSnapshot(
        True,
        devices=tuple(
            GpuDeviceStatus(str(index), gpu_id, "RTX", 24576, 0, 24576, 0)
            for index, gpu_id in enumerate(("GPU-a", "GPU-b", "GPU-c", "GPU-d"))
        ),
    )
    claims = compute_claim_candidates(
        resource_key="compute:tp",
        holder_key="tp",
        generation=1,
        consumer_resource_key="service:tp",
        requirement=ComputeRequirement(
            cpu_cores=1,
            memory_bytes=1,
            gpu_count=2,
            minimum_gpu_memory_bytes=1,
        ),
        hosts=(host,),
        authority=AuthoritySnapshot((), (), (), (), ()),
        placement_scope=scope,
        owner_scope=scope,
        scope_generation=1,
        scope_lease_id=None,
        gpu_runtime=runtime,
    )
    placement = compute_placement_from_claim(claims[0])
    assert placement.gpu_ids == ("GPU-a", "GPU-c")


def test_multi_gpu_topology_never_overrides_better_runtime_quality() -> None:
    scope = _scope("topology-pressure")
    host = ComputeHost(
        "host",
        scope,
        32,
        128 << 30,
        (
            ComputeGPU("GPU-a", 24 << 30, labels=(("numa_node", "0"),)),
            ComputeGPU("GPU-b", 24 << 30, labels=(("numa_node", "0"),)),
            ComputeGPU("GPU-c", 24 << 30, labels=(("numa_node", "1"),)),
        ),
    )
    runtime = GpuRuntimeSnapshot(
        True,
        devices=(
            GpuDeviceStatus("0", "GPU-a", "RTX", 24576, 0, 24576, 0),
            GpuDeviceStatus("1", "GPU-b", "RTX", 24576, 0, 24576, 90),
            GpuDeviceStatus("2", "GPU-c", "RTX", 24576, 0, 24576, 0),
        ),
    )
    claims = compute_claim_candidates(
        resource_key="compute:tp-pressure",
        holder_key="tp-pressure",
        generation=1,
        consumer_resource_key="service:tp-pressure",
        requirement=ComputeRequirement(
            cpu_cores=1,
            memory_bytes=1,
            gpu_count=2,
            minimum_gpu_memory_bytes=1,
        ),
        hosts=(host,),
        authority=AuthoritySnapshot((), (), (), (), ()),
        placement_scope=scope,
        owner_scope=scope,
        scope_generation=1,
        scope_lease_id=None,
        gpu_runtime=runtime,
    )
    placement = compute_placement_from_claim(claims[0])
    assert placement.gpu_ids == ("GPU-a", "GPU-c")
