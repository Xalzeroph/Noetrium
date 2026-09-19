from __future__ import annotations

import time

import pytest

from noetrium.platform import (
    ComputeDemand, ResourcePolicy, bind_experiment_resources, bind_research_execution_pool,
)
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind
from noetrium_platform.infrastructure.resources.compute.api import ComputeGPU, ComputeHost, ComputeLeasePolicy, GpuSharingMode
from noetrium_platform.infrastructure.resources.compute.runtime import InMemoryComputeInventory
from noetrium_platform.research.experimentation.experiment.api import (
    ExecutionMode,
    ExperimentDefinition,
    ExperimentUnitKind,
)
from tests.resource_compute_support import in_memory_compute_scheduler


def _definition(resource_policy_digest: str) -> ExperimentDefinition:
    return ExperimentDefinition(
        project_id="project-a",
        experiment_id="experiment-a",
        protocol_id="protocol-a",
        unit_kind=ExperimentUnitKind.TASK,
        execution_mode=ExecutionMode.BATCH,
        design_protocol_digest="1" * 64,
        observation_protocol_digest="2" * 64,
        analysis_plan_digest="3" * 64,
        implementation_digest="4" * 64,
        resource_policy_digest=resource_policy_digest,
    )


def test_resource_policy_digest_drives_compute_allocation_and_receipt() -> None:
    project = ScopeIdentity(ScopeKind.PROJECT, "project-a")
    owner = ScopeIdentity(ScopeKind.EXPERIMENT, "experiment-a")
    inventory = InMemoryComputeInventory()
    inventory.register_host(ComputeHost(
        "gpu-node", project, 32, 256,
        gpus=(ComputeGPU("GPU-small", 48, "gpu"), ComputeGPU("GPU-large", 80, "gpu")),
        labels=(("pool", "research"),),
    ))
    scheduler = in_memory_compute_scheduler(inventory)
    policy = ResourcePolicy(
        "one-gpu",
        ComputeDemand(
            cpu_cores=4,
            memory_bytes=32,
            gpu_count=1,
            minimum_gpu_memory_bytes=40,
            gpu_memory_reservation_bytes_per_device=20,
            gpu_memory_headroom_bytes=4,
            gpu_sharing_mode=GpuSharingMode.IDLE_ONLY,
            require_host_runtime=False,
            required_labels=(("pool", "research"),),
        ),
    )
    definition = _definition(policy.policy_digest)

    pool = bind_research_execution_pool()
    try:
        lease = bind_experiment_resources(
            definition,
            policy,
            allocation_id="allocation-a",
            owner_scope=owner,
            placement_scope=project,
            compute_scheduler=scheduler,
            execution_pool=pool,
        )
        try:
            receipt = lease.receipt
            assert receipt.policy_digest == policy.policy_digest
            assert receipt.owner_scope == owner
            assert receipt.placement_scope == project
            assert receipt.host_id == "gpu-node"
            assert receipt.cpu_cores == 4
            assert receipt.memory_bytes == 32
            assert receipt.gpu_ids == ("GPU-small",)
            assert receipt.lease_fencing_token == 1
            assert receipt.lease_expires_at_epoch_s is not None
            lease.assert_healthy()
            allocation = scheduler.allocations(scope=owner)[0]
            assert allocation.scope == owner
            assert allocation.host_id == "gpu-node"
        finally:
            lease.release()
        assert scheduler.allocations(scope=owner) == ()
    finally:
        pool.close()


def test_resource_binding_rejects_policy_identity_drift() -> None:
    frozen = ResourcePolicy("frozen", ComputeDemand(cpu_cores=1, memory_bytes=1))
    drifted = ResourcePolicy("drifted", ComputeDemand(cpu_cores=2, memory_bytes=1))
    with pytest.raises(ValueError, match="digest"):
        bind_experiment_resources(
            _definition(frozen.policy_digest),
            drifted,
            allocation_id="drift",
            owner_scope=ScopeIdentity(ScopeKind.EXPERIMENT, "experiment-a"),
        )


def test_model_service_only_policy_needs_no_compute_scheduler() -> None:
    policy = ResourcePolicy("model-service-only")
    lease = bind_experiment_resources(
        _definition(policy.policy_digest),
        policy,
        allocation_id="unused-id",
        owner_scope=ScopeIdentity(ScopeKind.EXPERIMENT, "experiment-a"),
    )
    assert lease.receipt.allocation_id is None
    assert lease.receipt.host_id is None
    lease.release()


def test_compute_binding_requires_shared_execution_pool_for_lease_safety() -> None:
    project = ScopeIdentity(ScopeKind.PROJECT, "project-a")
    inventory = InMemoryComputeInventory()
    inventory.register_host(ComputeHost("cpu-node", project, 8, 1024))
    scheduler = in_memory_compute_scheduler(inventory)
    policy = ResourcePolicy(
        "cpu-only",
        ComputeDemand(cpu_cores=1, memory_bytes=1, require_host_runtime=False),
    )
    with pytest.raises(RuntimeError, match="ResearchExecutionPool"):
        bind_experiment_resources(
            _definition(policy.policy_digest),
            policy,
            allocation_id="unsafe",
            owner_scope=ScopeIdentity(ScopeKind.EXPERIMENT, "experiment-a"),
            placement_scope=project,
            compute_scheduler=scheduler,
        )


def test_shared_pool_heartbeat_renews_compute_lease() -> None:
    project = ScopeIdentity(ScopeKind.PROJECT, "project-a")
    owner = ScopeIdentity(ScopeKind.EXPERIMENT, "experiment-heartbeat")
    inventory = InMemoryComputeInventory()
    inventory.register_host(ComputeHost("cpu-node", project, 8, 1024))
    scheduler = in_memory_compute_scheduler(inventory)
    policy = ResourcePolicy(
        "heartbeat",
        ComputeDemand(cpu_cores=1, memory_bytes=1, require_host_runtime=False),
    )
    pool = bind_research_execution_pool()
    try:
        lease = bind_experiment_resources(
            _definition(policy.policy_digest),
            policy,
            allocation_id="heartbeat",
            owner_scope=owner,
            placement_scope=project,
            compute_scheduler=scheduler,
            execution_pool=pool,
            compute_lease_policy=ComputeLeasePolicy(
                ttl_seconds=0.4, renewal_interval_seconds=0.05
            ),
        )
        initial = lease.receipt.lease_expires_at_epoch_s
        assert initial is not None
        deadline = time.time() + 1.0
        renewed = initial
        while time.time() < deadline and renewed <= initial:
            time.sleep(0.02)
            rows = scheduler.allocations(scope=owner)
            assert len(rows) == 1
            renewed = rows[0].lease_expires_at_epoch_s or 0.0
        assert renewed > initial
        lease.assert_healthy()
        lease.release()
        assert scheduler.allocations(scope=owner) == ()
    finally:
        pool.close()
