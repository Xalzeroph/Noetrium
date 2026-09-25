from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import threading

import pytest

from noetrium_platform.capabilities.model.deployment.api import (
    ModelDeploymentGeneration,
    ModelDeploymentStatus,
    ModelRuntimeState,
)
from noetrium_platform.capabilities.model.deployment.composition import (
    LocalModelReplicaPoolRuntime,
    ModelReplicaPoolRequest,
)
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.kernel.identity import ImmutableModelIdentity
from noetrium_platform.capabilities.model.stack.api import (
    ModelArtifactClosure,
    ModelStackSpec,
    RuntimeBuildIdentity,
)
from noetrium_platform.infrastructure.resources.allocation.api import (
    EndpointAllocation,
    EndpointAllocationRequest,
    EndpointAllocationState,
)
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeAllocation,
    ComputeGPU,
    ComputeHost,
    ComputeLeasePolicy,
    ComputePlacementUnavailable,
    ComputeRequirement,
    GpuSharingMode,
)


def _exception_leaf_messages(exc: BaseException) -> tuple[str, ...]:
    if isinstance(exc, BaseExceptionGroup):
        return tuple(
            message
            for child in exc.exceptions
            for message in _exception_leaf_messages(child)
        )
    return (str(exc),)


def _vllm_stack(
    *,
    engine_args: tuple[str, ...] = (),
    tensor_parallel: int = 1,
    data_parallel: int = 1,
    pipeline_parallel: int = 1,
) -> ModelStackSpec:
    return ModelStackSpec(
        ImmutableModelIdentity(
            "qwen",
            "qwen3-8b",
            "revision",
            "vllm",
            "test",
            "bfloat16",
            None,
            32768,
        ),
        ModelArtifactClosure("weights", "tokenizer", "config"),
        RuntimeBuildIdentity(
            "container",
            "engine",
            "lock",
            "cuda",
            "nccl",
            "torch",
            "kernels",
        ),
        tensor_parallel,
        data_parallel,
        1,
        pipeline_parallel,
        None,
        None,
        None,
        None,
        "fcfs",
        engine_args,
    )


class Catalog:
    def __init__(self):
        self.rows = {}

    def put_deployment(self, spec):
        self.rows[spec.deployment_id] = spec
        return spec


class Runtime:
    def __init__(self, catalog):
        self.catalog = catalog
        self.removed = []

    def status(self, deployment_id):
        spec = self.catalog.rows[deployment_id]
        return ModelDeploymentStatus(
            deployment_id,
            spec.service_id,
            spec.desired_state,
            ModelRuntimeState.RUNNING,
            100,
            f"ready:{deployment_id}",
        )

    def generation(self, deployment_id):
        spec = self.catalog.rows[deployment_id]
        return ModelDeploymentGeneration(
            deployment_id,
            canonical_digest(spec),
            canonical_digest({"fake-applied": deployment_id}),
        )

    def remove_deployment(self, generation):
        current = self.generation(generation.deployment_id)
        if current != generation:
            raise RuntimeError("stale model deployment generation")
        self.removed.append(generation.deployment_id)
        self.catalog.rows.pop(generation.deployment_id, None)
        return True


class Fleet:
    def __init__(self, catalog):
        self.catalog = catalog

    def reconcile(self):
        return tuple(
            ModelDeploymentStatus(
                spec.deployment_id,
                spec.service_id,
                spec.desired_state,
                ModelRuntimeState.RUNNING,
                100 + index,
                f"ready:{spec.deployment_id}",
            )
            for index, spec in enumerate(self.catalog.rows.values())
        )


class Scheduler:
    def __init__(self):
        self.host = ComputeHost(
            "node-a",
            PLATFORM_SCOPE,
            64,
            256 * 1024**3,
            (
                ComputeGPU("GPU-a", 48 * 1024**3, "GPU"),
                ComputeGPU("GPU-b", 48 * 1024**3, "GPU"),
            ),
        )
        self.next = 0
        self.released = []
        self.requirements = []
        self.rows = {}

    def candidates(self, requirement, *, scope=None):
        return (self.host,)

    def allocate(
        self,
        allocation_id,
        scope,
        requirement,
        *,
        placement_scope=None,
        ttl_seconds=None,
        now=None,
    ):
        self.requirements.append(requirement)
        if self.next >= 2:
            raise ComputePlacementUnavailable(requirement)
        gpu = self.host.gpus[self.next]
        self.next += 1
        row = ComputeAllocation(
            allocation_id,
            scope,
            self.host.host_id,
            requirement.cpu_cores,
            requirement.memory_bytes,
            (gpu.gpu_id,),
            self.next,
            9999999999.0,
        )
        self.rows[row.allocation_id] = row
        return row

    def confirm_bound(self, proof):
        current = self.rows[proof.allocation_id]
        if (
            proof.host_id != current.host_id
            or proof.gpu_ids != current.gpu_ids
            or proof.lease_fencing_token != current.lease_fencing_token
        ):
            raise RuntimeError("stale compute binding generation")
        bound = replace(
            current,
            binding_proof_digest=proof.digest(),
            binding_binder_identity_digest=proof.binder_identity_digest,
            binding_evidence_ref=proof.evidence_ref,
            bound_at_epoch_s=proof.observed_at_epoch_s,
        )
        self.rows[proof.allocation_id] = bound
        return bound

    def replace_bound(
        self,
        proof,
        *,
        previous_binding_proof_digest,
    ):
        current = self.rows[proof.allocation_id]
        if current.binding_proof_digest != previous_binding_proof_digest:
            raise RuntimeError("stale compute binding replacement")
        if current.binding_binder_identity_digest == proof.binder_identity_digest:
            raise RuntimeError("compute replacement requires new binder")
        rebound = replace(
            current,
            binding_proof_digest=proof.digest(),
            binding_binder_identity_digest=proof.binder_identity_digest,
            binding_evidence_ref=proof.evidence_ref,
            bound_at_epoch_s=proof.observed_at_epoch_s,
        )
        self.rows[proof.allocation_id] = rebound
        return rebound

    def release(self, allocation):
        self.released.append(allocation.allocation_id)
        self.rows.pop(allocation.allocation_id, None)

    def recover_release(self, allocation):
        self.release(allocation)


class Endpoints:
    def __init__(self):
        self.rows = {}
        self.released = []

    def allocate_auto(self, **kwargs):
        port = 24000 + len(self.rows)
        request = EndpointAllocationRequest(
            allocation_id=kwargs["allocation_id"],
            holder_scope=kwargs["holder_scope"],
            purpose=kwargs["purpose"],
            host=kwargs["host"],
            candidate_ports=(port,),
            owner_scope=kwargs["owner_scope"],
            ownership=kwargs["ownership"],
        )
        return self.allocate(request)

    def allocate(self, request):
        row = EndpointAllocation(
            request.allocation_id,
            request.candidates()[0],
            f"lease:{request.allocation_id}",
            request.holder_scope,
            request.purpose,
            request.digest(),
            lease_fencing_token=len(self.rows) + 1,
            lease_expires_at_epoch_s=9999999999.0,
        )
        self.rows[row.allocation_id] = row
        return row

    def confirm_bound(self, proof):
        current = self.rows[proof.allocation_id]
        bound = replace(
            current,
            state=EndpointAllocationState.BOUND,
            binding_proof_digest=proof.digest(),
            binding_binder_identity_digest=proof.binder_identity_digest,
            binding_evidence_ref=proof.evidence_ref,
            bound_at_epoch_s=proof.observed_at_epoch_s,
        )
        self.rows[proof.allocation_id] = bound
        return bound

    def replace_bound(
        self,
        proof,
        *,
        expected_previous_binding_proof_digest,
    ):
        current = self.rows[proof.allocation_id]
        if current.binding_proof_digest != expected_previous_binding_proof_digest:
            raise RuntimeError("stale endpoint binding replacement")
        if current.binding_binder_identity_digest == proof.binder_identity_digest:
            raise RuntimeError("endpoint replacement requires new binder")
        rebound = replace(
            current,
            binding_proof_digest=proof.digest(),
            binding_binder_identity_digest=proof.binder_identity_digest,
            binding_evidence_ref=proof.evidence_ref,
            bound_at_epoch_s=proof.observed_at_epoch_s,
        )
        self.rows[proof.allocation_id] = rebound
        return rebound

    def release(self, allocation):
        self.released.append(allocation.allocation_id)
        current = self.rows[allocation.allocation_id]
        if current.lease_fencing_token != allocation.lease_fencing_token:
            raise RuntimeError("stale endpoint allocation generation")
        released = replace(current, state=EndpointAllocationState.RELEASED)
        self.rows[allocation.allocation_id] = released
        return released

    def recover_release(self, allocation, *, now=None):
        del now
        return self.release(allocation)


class Guard:
    def __init__(self, ids):
        self.ids = ids
        self.started = False
        self.closed = False

    def start(self):
        self.started = True

    def assert_healthy(self):
        assert self.started and not self.closed

    def close(self):
        self.closed = True


class ComputeGuards:
    policy = ComputeLeasePolicy(ttl_seconds=120.0, renewal_interval_seconds=30.0)

    def __init__(self):
        self.created = []

    def create(self, ids):
        guard = Guard(ids)
        self.created.append(guard)
        return guard


class EndpointGuards:
    def __init__(self):
        self.created = []

    def create(self, ids):
        guard = Guard(ids)
        self.created.append(guard)
        return guard


def test_auto_model_replica_pool_exhausts_available_gpu_capacity_without_gpu_or_port_input(
    tmp_path,
) -> None:
    catalog = Catalog()
    runtime = Runtime(catalog)
    scheduler = Scheduler()
    endpoints = Endpoints()
    compute_guards = ComputeGuards()
    endpoint_guards = EndpointGuards()
    pool = LocalModelReplicaPoolRuntime(
        deployment_catalog=catalog,
        deployment_runtime=runtime,
        fleet=Fleet(catalog),
        compute_scheduler=scheduler,
        endpoint_allocations=endpoints,
        compute_lease_guards=compute_guards,
        endpoint_lease_guards=endpoint_guards,
    )

    lease = pool.ensure(
        ModelReplicaPoolRequest(
            pool_id="qwen",
            scope=PLATFORM_SCOPE,
            model_id="qwen3-8b",
            engine="vllm",
            python_environment_id="vllm",
            cwd=Path(tmp_path),
            compute=ComputeRequirement(
                cpu_cores=2,
                memory_bytes=1024,
                gpu_count=1,
                minimum_gpu_memory_bytes=40 * 1024**3,
            ),
        )
    )

    assert len(lease.report.placements) == 2
    assert tuple(row.deployment.gpu_devices for row in lease.report.placements) == (
        ("GPU-a",),
        ("GPU-b",),
    )
    assert all(row.endpoint.state is EndpointAllocationState.BOUND for row in lease.report.placements)
    assert all(
        row.endpoint.binding_binder_identity_digest
        == row.generation.applied_runtime_digest
        for row in lease.report.placements
    )
    assert all(row.compute.is_bound for row in lease.report.placements)
    assert all(
        row.compute.binding_binder_identity_digest
        == row.generation.applied_runtime_digest
        for row in lease.report.placements
    )
    assert all(
        row.endpoint.binding_binder_identity_digest
        != canonical_digest(row.deployment)
        for row in lease.report.placements
    )
    assert all(row.deployment.readiness_url for row in lease.report.placements)
    assert compute_guards.created[0].started
    assert endpoint_guards.created[0].started
    lease.assert_healthy()

    lease.close()
    assert len(runtime.removed) == 2
    assert len(scheduler.released) == 2
    assert len(endpoints.released) == 2
    assert compute_guards.created[0].closed
    assert endpoint_guards.created[0].closed


def test_model_pool_rebinds_compute_and_endpoint_after_runtime_recovery(
    tmp_path,
) -> None:
    class RecoveringRuntime(Runtime):
        def __init__(self, catalog):
            super().__init__(catalog)
            self.epoch = 1

        def generation(self, deployment_id):
            spec = self.catalog.rows[deployment_id]
            return ModelDeploymentGeneration(
                deployment_id,
                canonical_digest(spec),
                canonical_digest(
                    {
                        "fake-applied": deployment_id,
                        "epoch": self.epoch,
                    }
                ),
            )

    catalog = Catalog()
    runtime = RecoveringRuntime(catalog)
    scheduler = Scheduler()
    endpoints = Endpoints()
    pool = LocalModelReplicaPoolRuntime(
        deployment_catalog=catalog,
        deployment_runtime=runtime,
        fleet=Fleet(catalog),
        compute_scheduler=scheduler,
        endpoint_allocations=endpoints,
        compute_lease_guards=ComputeGuards(),
        endpoint_lease_guards=EndpointGuards(),
    )

    lease = pool.ensure(
        ModelReplicaPoolRequest(
            pool_id="recovered-qwen",
            scope=PLATFORM_SCOPE,
            model_id="qwen3-8b",
            engine="vllm",
            python_environment_id="vllm",
            cwd=Path(tmp_path),
            compute=ComputeRequirement(
                cpu_cores=2,
                memory_bytes=1024,
                gpu_count=1,
                minimum_gpu_memory_bytes=40 * 1024**3,
            ),
            replica_count=1,
        )
    )
    row = lease.report.placements[0]
    original = row.generation.applied_runtime_digest
    assert original is not None

    runtime.epoch = 2
    current = runtime.generation(row.deployment_id)
    assert current.applied_runtime_digest != original

    lease.assert_healthy()

    compute = scheduler.rows[row.compute.allocation_id]
    endpoint = endpoints.rows[row.endpoint.allocation_id]
    assert (
        compute.binding_binder_identity_digest
        == current.applied_runtime_digest
    )
    assert (
        endpoint.binding_binder_identity_digest
        == current.applied_runtime_digest
    )

    lease.close()
    assert runtime.removed == [row.deployment_id]
    assert scheduler.released == [row.compute.allocation_id]
    assert endpoints.released == [row.endpoint.allocation_id]


def test_model_pool_binding_retries_torn_status_generation_observation(
    tmp_path,
) -> None:
    class RacingRuntime(Runtime):
        def __init__(self, catalog):
            super().__init__(catalog)
            self.epoch = 1
            self.flip_on_status = True

        def status(self, deployment_id):
            status = super().status(deployment_id)
            if self.flip_on_status:
                self.flip_on_status = False
                self.epoch = 2
            return status

        def generation(self, deployment_id):
            spec = self.catalog.rows[deployment_id]
            return ModelDeploymentGeneration(
                deployment_id,
                canonical_digest(spec),
                canonical_digest(
                    {
                        "fake-applied": deployment_id,
                        "epoch": self.epoch,
                    }
                ),
            )

    catalog = Catalog()
    runtime = RacingRuntime(catalog)
    scheduler = Scheduler()
    endpoints = Endpoints()
    pool = LocalModelReplicaPoolRuntime(
        deployment_catalog=catalog,
        deployment_runtime=runtime,
        fleet=Fleet(catalog),
        compute_scheduler=scheduler,
        endpoint_allocations=endpoints,
        compute_lease_guards=ComputeGuards(),
        endpoint_lease_guards=EndpointGuards(),
    )

    lease = pool.ensure(
        ModelReplicaPoolRequest(
            pool_id="torn-observation",
            scope=PLATFORM_SCOPE,
            model_id="qwen3-8b",
            engine="vllm",
            python_environment_id="vllm",
            cwd=Path(tmp_path),
            compute=ComputeRequirement(
                cpu_cores=2,
                memory_bytes=1024,
                gpu_count=1,
                minimum_gpu_memory_bytes=40 * 1024**3,
            ),
            replica_count=1,
        )
    )

    row = lease.report.placements[0]
    current = runtime.generation(row.deployment_id)
    assert current.applied_runtime_digest is not None
    assert (
        scheduler.rows[row.compute.allocation_id]
        .binding_binder_identity_digest
        == current.applied_runtime_digest
    )
    assert (
        endpoints.rows[row.endpoint.allocation_id]
        .binding_binder_identity_digest
        == current.applied_runtime_digest
    )
    lease.close()


def test_model_pool_rebinds_if_runtime_restarts_between_compute_and_endpoint_binding(
    tmp_path,
) -> None:
    class RestartingRuntime(Runtime):
        def __init__(self, catalog):
            super().__init__(catalog)
            self.epoch = 1

        def generation(self, deployment_id):
            spec = self.catalog.rows[deployment_id]
            return ModelDeploymentGeneration(
                deployment_id,
                canonical_digest(spec),
                canonical_digest(
                    {
                        "fake-applied": deployment_id,
                        "epoch": self.epoch,
                    }
                ),
            )

    class RestartDuringEndpointBind(Endpoints):
        def __init__(self, runtime):
            super().__init__()
            self.runtime = runtime
            self.restarted = False

        def confirm_bound(self, proof):
            if not self.restarted:
                self.restarted = True
                self.runtime.epoch = 2
            return super().confirm_bound(proof)

    catalog = Catalog()
    runtime = RestartingRuntime(catalog)
    scheduler = Scheduler()
    endpoints = RestartDuringEndpointBind(runtime)
    pool = LocalModelReplicaPoolRuntime(
        deployment_catalog=catalog,
        deployment_runtime=runtime,
        fleet=Fleet(catalog),
        compute_scheduler=scheduler,
        endpoint_allocations=endpoints,
        compute_lease_guards=ComputeGuards(),
        endpoint_lease_guards=EndpointGuards(),
    )

    lease = pool.ensure(
        ModelReplicaPoolRequest(
            pool_id="mid-bind-restart",
            scope=PLATFORM_SCOPE,
            model_id="qwen3-8b",
            engine="vllm",
            python_environment_id="vllm",
            cwd=Path(tmp_path),
            compute=ComputeRequirement(
                cpu_cores=2,
                memory_bytes=1024,
                gpu_count=1,
                minimum_gpu_memory_bytes=40 * 1024**3,
            ),
            replica_count=1,
        )
    )

    row = lease.report.placements[0]
    current = runtime.generation(row.deployment_id)
    assert current.applied_runtime_digest is not None
    assert runtime.epoch == 2
    assert (
        scheduler.rows[row.compute.allocation_id]
        .binding_binder_identity_digest
        == current.applied_runtime_digest
    )
    assert (
        endpoints.rows[row.endpoint.allocation_id]
        .binding_binder_identity_digest
        == current.applied_runtime_digest
    )
    lease.close()


def test_model_pool_generation_churn_fails_closed_without_releasing_resources(
    tmp_path,
) -> None:
    class ChurningRuntime(Runtime):
        def __init__(self, catalog):
            super().__init__(catalog)
            self.epoch = 1
            self.churning = False

        def status(self, deployment_id):
            status = super().status(deployment_id)
            if self.churning:
                self.epoch += 1
            return status

        def generation(self, deployment_id):
            spec = self.catalog.rows[deployment_id]
            return ModelDeploymentGeneration(
                deployment_id,
                canonical_digest(spec),
                canonical_digest(
                    {
                        "fake-applied": deployment_id,
                        "epoch": self.epoch,
                    }
                ),
            )

    catalog = Catalog()
    runtime = ChurningRuntime(catalog)
    scheduler = Scheduler()
    endpoints = Endpoints()
    compute_guards = ComputeGuards()
    endpoint_guards = EndpointGuards()
    pool = LocalModelReplicaPoolRuntime(
        deployment_catalog=catalog,
        deployment_runtime=runtime,
        fleet=Fleet(catalog),
        compute_scheduler=scheduler,
        endpoint_allocations=endpoints,
        compute_lease_guards=compute_guards,
        endpoint_lease_guards=endpoint_guards,
    )

    lease = pool.ensure(
        ModelReplicaPoolRequest(
            pool_id="generation-churn",
            scope=PLATFORM_SCOPE,
            model_id="qwen3-8b",
            engine="vllm",
            python_environment_id="vllm",
            cwd=Path(tmp_path),
            compute=ComputeRequirement(
                cpu_cores=2,
                memory_bytes=1024,
                gpu_count=1,
                minimum_gpu_memory_bytes=40 * 1024**3,
            ),
            replica_count=1,
        )
    )
    row = lease.report.placements[0]
    original_compute = scheduler.rows[row.compute.allocation_id]
    original_endpoint = endpoints.rows[row.endpoint.allocation_id]

    runtime.churning = True
    with pytest.raises(RuntimeError, match="did not stabilize"):
        lease.assert_healthy()

    assert pool.active_lease_count == 1
    assert scheduler.released == []
    assert endpoints.released == []
    assert scheduler.rows[row.compute.allocation_id] == original_compute
    assert endpoints.rows[row.endpoint.allocation_id] == original_endpoint
    assert compute_guards.created[0].closed is False
    assert endpoint_guards.created[0].closed is False

    runtime.churning = False
    lease.close()
    assert scheduler.released == [row.compute.allocation_id]
    assert endpoints.released == [row.endpoint.allocation_id]
    assert compute_guards.created[0].closed is True
    assert endpoint_guards.created[0].closed is True


def test_model_endpoint_binding_requires_applied_runtime_generation(
    tmp_path,
) -> None:
    class NoAppliedRuntime(Runtime):
        def generation(self, deployment_id):
            spec = self.catalog.rows[deployment_id]
            return ModelDeploymentGeneration(
                deployment_id,
                canonical_digest(spec),
                None,
            )

    catalog = Catalog()
    runtime = NoAppliedRuntime(catalog)
    scheduler = Scheduler()
    endpoints = Endpoints()
    pool = LocalModelReplicaPoolRuntime(
        deployment_catalog=catalog,
        deployment_runtime=runtime,
        fleet=Fleet(catalog),
        compute_scheduler=scheduler,
        endpoint_allocations=endpoints,
        compute_lease_guards=ComputeGuards(),
        endpoint_lease_guards=EndpointGuards(),
    )

    with pytest.raises(RuntimeError, match="no applied runtime generation"):
        pool.ensure(
            ModelReplicaPoolRequest(
                pool_id="no-applied-runtime",
                scope=PLATFORM_SCOPE,
                model_id="qwen3-8b",
                engine="vllm",
                python_environment_id="vllm",
                cwd=Path(tmp_path),
                compute=ComputeRequirement(
                    cpu_cores=2,
                    memory_bytes=1024,
                    gpu_count=1,
                    minimum_gpu_memory_bytes=40 * 1024**3,
                ),
                replica_count=1,
            )
        )

    row = next(iter(endpoints.rows.values()))
    assert row.state is EndpointAllocationState.RELEASED
    assert row.binding_binder_identity_digest is None
    assert scheduler.released


def test_auto_model_replica_pool_uses_multiple_shared_slots_on_one_gpu(
    tmp_path,
) -> None:
    class SharedScheduler(Scheduler):
        def __init__(self):
            super().__init__()
            self.host = ComputeHost(
                "node-a",
                PLATFORM_SCOPE,
                64,
                256 * 1024**3,
                (ComputeGPU("GPU-shared", 48 * 1024**3, "GPU"),),
            )

        def allocate(
            self,
            allocation_id,
            scope,
            requirement,
            *,
            placement_scope=None,
            ttl_seconds=None,
            now=None,
        ):
            del placement_scope, ttl_seconds, now
            self.requirements.append(requirement)
            if self.next >= 2:
                raise ComputePlacementUnavailable(requirement)
            self.next += 1
            row = ComputeAllocation(
                allocation_id=allocation_id,
                scope=scope,
                host_id=self.host.host_id,
                cpu_cores=requirement.cpu_cores,
                memory_bytes=requirement.memory_bytes,
                gpu_ids=("GPU-shared",),
                lease_fencing_token=self.next,
                lease_expires_at_epoch_s=9999999999.0,
                gpu_sharing_mode=requirement.gpu_sharing_mode,
                gpu_memory_reservation_bytes=(
                    requirement.required_gpu_free_memory_bytes,
                ),
            )
            self.rows[row.allocation_id] = row
            return row

    catalog = Catalog()
    scheduler = SharedScheduler()
    pool = LocalModelReplicaPoolRuntime(
        deployment_catalog=catalog,
        deployment_runtime=Runtime(catalog),
        fleet=Fleet(catalog),
        compute_scheduler=scheduler,
        endpoint_allocations=Endpoints(),
        compute_lease_guards=ComputeGuards(),
        endpoint_lease_guards=EndpointGuards(),
    )

    lease = pool.ensure(
        ModelReplicaPoolRequest(
            pool_id="shared-qwen",
            scope=PLATFORM_SCOPE,
            model_id="qwen3-8b",
            engine="vllm",
            python_environment_id="vllm",
            cwd=Path(tmp_path),
            compute=ComputeRequirement(
                cpu_cores=2,
                memory_bytes=1024,
                gpu_count=1,
                required_gpu_free_memory_bytes=16 * 1024**3,
                gpu_sharing_mode=GpuSharingMode.PREFER_IDLE_ALLOW_SHARED,
            ),
        )
    )

    assert len(lease.report.placements) == 2
    assert {
        row.compute.gpu_ids
        for row in lease.report.placements
    } == {("GPU-shared",)}
    assert all(row.compute.is_bound for row in lease.report.placements)
    lease.close()


def test_auto_model_replica_pool_launches_frozen_vllm_engine_args(
    tmp_path,
) -> None:
    catalog = Catalog()
    runtime = Runtime(catalog)
    scheduler = Scheduler()
    pool = LocalModelReplicaPoolRuntime(
        deployment_catalog=catalog,
        deployment_runtime=runtime,
        fleet=Fleet(catalog),
        compute_scheduler=scheduler,
        endpoint_allocations=Endpoints(),
        compute_lease_guards=ComputeGuards(),
        endpoint_lease_guards=EndpointGuards(),
    )
    stack = _vllm_stack(
        engine_args=(
            "--gpu-memory-utilization",
            "0.97",
            "--max-num-seqs",
            "64",
            "--enable-prefix-caching",
        )
    )
    lease = pool.ensure(
        ModelReplicaPoolRequest(
            pool_id="qwen-frozen",
            scope=PLATFORM_SCOPE,
            model_id="qwen3-8b",
            engine="vllm",
            python_environment_id="vllm",
            cwd=Path(tmp_path),
            compute=ComputeRequirement(
                cpu_cores=2,
                memory_bytes=1024,
                gpu_count=1,
                minimum_gpu_memory_bytes=40 * 1024**3,
            ),
            model_stack=stack,
            replica_count=1,
        )
    )
    argv = lease.report.placements[0].deployment.argv
    assert argv[argv.index("--gpu-memory-utilization") + 1] == "0.97"
    assert argv[argv.index("--max-num-seqs") + 1] == "64"
    assert "--enable-prefix-caching" in argv
    assert f"model-stack:{stack.digest()}" in lease.report.placements[0].deployment.tags
    lease.close()


def test_frozen_vllm_stack_drives_physical_vram_and_cpu_offload_reservation(
    tmp_path,
) -> None:
    catalog = Catalog()
    scheduler = Scheduler()
    pool = LocalModelReplicaPoolRuntime(
        deployment_catalog=catalog,
        deployment_runtime=Runtime(catalog),
        fleet=Fleet(catalog),
        compute_scheduler=scheduler,
        endpoint_allocations=Endpoints(),
        compute_lease_guards=ComputeGuards(),
        endpoint_lease_guards=EndpointGuards(),
    )
    stack = _vllm_stack(
        engine_args=(
            "--gpu-memory-utilization=0.75",
            "--cpu-offload-gb",
            "2.5",
        )
    )
    base_memory = 1024**3
    lease = pool.ensure(
        ModelReplicaPoolRequest(
            pool_id="qwen-resources",
            scope=PLATFORM_SCOPE,
            model_id="qwen3-8b",
            engine="vllm",
            python_environment_id="vllm",
            cwd=Path(tmp_path),
            compute=ComputeRequirement(
                cpu_cores=2,
                memory_bytes=base_memory,
                gpu_count=1,
                minimum_gpu_memory_bytes=40 * 1024**3,
            ),
            model_stack=stack,
            replica_count=1,
        )
    )

    effective = scheduler.requirements[0]
    assert effective.required_gpu_memory_fraction == 0.75
    assert effective.memory_bytes == base_memory + int(2.5 * 1024**3)
    assert lease.report.placements[0].compute.memory_bytes == effective.memory_bytes
    lease.close()


def test_frozen_vllm_stack_rejects_ad_hoc_runtime_drift(tmp_path) -> None:
    stack = _vllm_stack(engine_args=("--max-num-seqs", "64"))
    try:
        ModelReplicaPoolRequest(
            pool_id="qwen-drift",
            scope=PLATFORM_SCOPE,
            model_id="qwen3-8b",
            engine="vllm",
            python_environment_id="vllm",
            cwd=Path(tmp_path),
            compute=ComputeRequirement(
                cpu_cores=2,
                memory_bytes=1024,
                gpu_count=1,
                minimum_gpu_memory_bytes=40 * 1024**3,
            ),
            model_stack=stack,
            extra_args=("--max-num-seqs", "128"),
        )
    except ValueError as exc:
        assert "extra_args are forbidden" in str(exc)
    else:
        raise AssertionError("frozen vLLM stack accepted ad-hoc engine argument drift")


def test_auto_vllm_pool_rejects_internal_dp_without_owned_rpc_endpoint(
    tmp_path,
) -> None:
    stack = _vllm_stack(data_parallel=2)
    try:
        ModelReplicaPoolRequest(
            pool_id="qwen-dp",
            scope=PLATFORM_SCOPE,
            model_id="qwen3-8b",
            engine="vllm",
            python_environment_id="vllm",
            cwd=Path(tmp_path),
            compute=ComputeRequirement(
                cpu_cores=2,
                memory_bytes=1024,
                gpu_count=2,
                minimum_gpu_memory_bytes=40 * 1024**3,
            ),
            model_stack=stack,
        )
    except ValueError as exc:
        assert "auxiliary RPC endpoint" in str(exc)
    else:
        raise AssertionError("vLLM internal DP was admitted without RPC endpoint authority")


def test_auto_model_replica_pool_does_not_mask_scheduler_failure(tmp_path) -> None:
    class BrokenScheduler(Scheduler):
        def allocate(self, *args, **kwargs):
            if self.next >= 1:
                raise RuntimeError("scheduler database corrupted")
            return super().allocate(*args, **kwargs)

    catalog = Catalog()
    runtime = Runtime(catalog)
    scheduler = BrokenScheduler()
    endpoints = Endpoints()
    pool = LocalModelReplicaPoolRuntime(
        deployment_catalog=catalog,
        deployment_runtime=runtime,
        fleet=Fleet(catalog),
        compute_scheduler=scheduler,
        endpoint_allocations=endpoints,
        compute_lease_guards=ComputeGuards(),
        endpoint_lease_guards=EndpointGuards(),
    )

    try:
        pool.ensure(
            ModelReplicaPoolRequest(
                pool_id="qwen",
                scope=PLATFORM_SCOPE,
                model_id="qwen3-8b",
                engine="vllm",
                python_environment_id="vllm",
                cwd=Path(tmp_path),
                compute=ComputeRequirement(
                    cpu_cores=2,
                    memory_bytes=1024,
                    gpu_count=1,
                    minimum_gpu_memory_bytes=40 * 1024**3,
                ),
            )
        )
    except RuntimeError as exc:
        assert str(exc) == "scheduler database corrupted"
    else:
        raise AssertionError("unexpected scheduler failures must not be treated as exhaustion")


def test_failed_creation_retains_cleanup_generation_until_retry(
    tmp_path,
) -> None:
    class FailOnceCleanupRuntime(Runtime):
        def __init__(self, catalog):
            super().__init__(catalog)
            self.fail_cleanup_once = True

        def remove_deployment(self, generation):
            if self.fail_cleanup_once:
                self.fail_cleanup_once = False
                raise RuntimeError("simulated creation cleanup failure")
            return super().remove_deployment(generation)

    class RejectingFleet(Fleet):
        def reconcile(self):
            rows = super().reconcile()
            return tuple(
                replace(
                    row,
                    runtime_state=ModelRuntimeState.ERROR,
                    detail="simulated startup failure",
                )
                for row in rows
            )

    catalog = Catalog()
    runtime = FailOnceCleanupRuntime(catalog)
    scheduler = Scheduler()
    endpoints = Endpoints()
    compute_guards = ComputeGuards()
    endpoint_guards = EndpointGuards()
    pool = LocalModelReplicaPoolRuntime(
        deployment_catalog=catalog,
        deployment_runtime=runtime,
        fleet=RejectingFleet(catalog),
        compute_scheduler=scheduler,
        endpoint_allocations=endpoints,
        compute_lease_guards=compute_guards,
        endpoint_lease_guards=endpoint_guards,
    )
    request = ModelReplicaPoolRequest(
        pool_id="creation-cleanup-retry",
        scope=PLATFORM_SCOPE,
        model_id="qwen3-8b",
        engine="vllm",
        python_environment_id="vllm",
        cwd=Path(tmp_path),
        compute=ComputeRequirement(
            cpu_cores=2,
            memory_bytes=1024,
            gpu_count=1,
            minimum_gpu_memory_bytes=40 * 1024**3,
        ),
        replica_count=1,
    )

    with pytest.raises(
        ExceptionGroup,
        match="creation failed with pending cleanup",
    ) as raised:
        pool.ensure(request)
    messages = _exception_leaf_messages(raised.value)
    assert any("simulated startup failure" in message for message in messages)
    assert any(
        "simulated creation cleanup failure" in message
        for message in messages
    )
    assert pool.pending_cleanup_count == 1

    # Failed service convergence must keep both physical resource families
    # fenced. Releasing them here could allow a replacement generation to
    # overlap the still-unproven model process.
    assert scheduler.released == []
    assert endpoints.released == []
    assert compute_guards.created[0].closed is False
    assert endpoint_guards.created[0].closed is False

    pool.close_all()

    assert pool.pending_cleanup_count == 0
    assert len(runtime.removed) == 1
    assert len(scheduler.released) == 1
    assert len(endpoints.released) == 1
    assert compute_guards.created[0].closed is True
    assert endpoint_guards.created[0].closed is True


def test_failed_creation_uses_recovery_retirement_after_exact_stop(
    tmp_path,
) -> None:
    class RejectingFleet(Fleet):
        def reconcile(self):
            rows = super().reconcile()
            return tuple(
                replace(
                    row,
                    runtime_state=ModelRuntimeState.ERROR,
                    detail="simulated startup failure",
                )
                for row in rows
            )

    class RecoveryOnlyScheduler(Scheduler):
        def release(self, allocation):
            raise AssertionError(
                "failed-creation cleanup must not use live compute release"
            )

        def recover_release(self, allocation):
            Scheduler.release(self, allocation)

    class RecoveryOnlyEndpoints(Endpoints):
        def release(self, allocation):
            raise AssertionError(
                "failed-creation cleanup must not use live endpoint release"
            )

        def recover_release(self, allocation, *, now=None):
            del now
            return Endpoints.release(self, allocation)

    catalog = Catalog()
    runtime = Runtime(catalog)
    scheduler = RecoveryOnlyScheduler()
    endpoints = RecoveryOnlyEndpoints()
    compute_guards = ComputeGuards()
    endpoint_guards = EndpointGuards()
    pool = LocalModelReplicaPoolRuntime(
        deployment_catalog=catalog,
        deployment_runtime=runtime,
        fleet=RejectingFleet(catalog),
        compute_scheduler=scheduler,
        endpoint_allocations=endpoints,
        compute_lease_guards=compute_guards,
        endpoint_lease_guards=endpoint_guards,
    )

    with pytest.raises(RuntimeError, match="automatic model replica failed"):
        pool.ensure(
            ModelReplicaPoolRequest(
                pool_id="failed-creation-recovery-retirement",
                scope=PLATFORM_SCOPE,
                model_id="qwen3-8b",
                engine="vllm",
                python_environment_id="vllm",
                cwd=Path(tmp_path),
                compute=ComputeRequirement(
                    cpu_cores=2,
                    memory_bytes=1024,
                    gpu_count=1,
                    minimum_gpu_memory_bytes=40 * 1024**3,
                ),
                replica_count=1,
            )
        )

    assert pool.pending_cleanup_count == 0
    assert pool.active_lease_count == 0
    assert len(runtime.removed) == 1
    assert len(scheduler.released) == 1
    assert len(endpoints.released) == 1
    assert compute_guards.created[0].closed is True
    assert endpoint_guards.created[0].closed is True


def test_model_replica_pool_close_uses_recovery_retirement_after_exact_stop(
    tmp_path,
) -> None:
    class RecoveryOnlyScheduler(Scheduler):
        def release(self, allocation):
            raise AssertionError("live compute release must not be used after model stop")

        def recover_release(self, allocation):
            Scheduler.release(self, allocation)

    class RecoveryOnlyEndpoints(Endpoints):
        def release(self, allocation):
            raise AssertionError("live endpoint release must not be used after model stop")

        def recover_release(self, allocation, *, now=None):
            del now
            return Endpoints.release(self, allocation)

    catalog = Catalog()
    runtime = Runtime(catalog)
    scheduler = RecoveryOnlyScheduler()
    endpoints = RecoveryOnlyEndpoints()
    pool = LocalModelReplicaPoolRuntime(
        deployment_catalog=catalog,
        deployment_runtime=runtime,
        fleet=Fleet(catalog),
        compute_scheduler=scheduler,
        endpoint_allocations=endpoints,
        compute_lease_guards=ComputeGuards(),
        endpoint_lease_guards=EndpointGuards(),
    )
    lease = pool.ensure(
        ModelReplicaPoolRequest(
            pool_id="recovery-retirement",
            scope=PLATFORM_SCOPE,
            model_id="qwen3-8b",
            engine="vllm",
            python_environment_id="vllm",
            cwd=Path(tmp_path),
            compute=ComputeRequirement(
                cpu_cores=2,
                memory_bytes=1024,
                gpu_count=1,
                minimum_gpu_memory_bytes=40 * 1024**3,
            ),
            replica_count=1,
        )
    )

    lease.close()

    assert len(runtime.removed) == 1
    assert len(scheduler.released) == 1
    assert len(endpoints.released) == 1
    assert pool.active_lease_count == 0


def test_model_replica_pool_close_is_idempotent_after_prior_exact_retirement(
    tmp_path,
) -> None:
    class IdempotentRetirementRuntime(Runtime):
        def remove_deployment(self, generation):
            if generation.deployment_id not in self.catalog.rows:
                return True
            return super().remove_deployment(generation)

    catalog = Catalog()
    runtime = IdempotentRetirementRuntime(catalog)
    scheduler = Scheduler()
    endpoints = Endpoints()
    pool = LocalModelReplicaPoolRuntime(
        deployment_catalog=catalog,
        deployment_runtime=runtime,
        fleet=Fleet(catalog),
        compute_scheduler=scheduler,
        endpoint_allocations=endpoints,
        compute_lease_guards=ComputeGuards(),
        endpoint_lease_guards=EndpointGuards(),
    )
    lease = pool.ensure(
        ModelReplicaPoolRequest(
            pool_id="prior-exact-retirement",
            scope=PLATFORM_SCOPE,
            model_id="qwen3-8b",
            engine="vllm",
            python_environment_id="vllm",
            cwd=Path(tmp_path),
            compute=ComputeRequirement(
                cpu_cores=2,
                memory_bytes=1024,
                gpu_count=1,
                minimum_gpu_memory_bytes=40 * 1024**3,
            ),
            replica_count=1,
        )
    )
    placement = lease.report.placements[0]

    assert runtime.remove_deployment(placement.generation) is True
    assert placement.deployment_id not in catalog.rows

    lease.close()

    assert len(scheduler.released) == 1
    assert len(endpoints.released) == 1
    assert pool.active_lease_count == 0


def test_failed_creation_does_not_treat_missing_desired_as_physical_convergence(
    tmp_path,
) -> None:
    class DesiredLossRuntime(Runtime):
        def __init__(self, catalog):
            super().__init__(catalog)
            self.applied_uncertain = True

        def remove_deployment(self, generation):
            if generation.deployment_id not in self.catalog.rows:
                if self.applied_uncertain:
                    raise RuntimeError("applied generation still physically uncertain")
                self.removed.append(generation.deployment_id)
                return True
            return super().remove_deployment(generation)

    class LosingDesiredFleet(Fleet):
        def reconcile(self):
            rows = super().reconcile()
            self.catalog.rows.clear()
            return tuple(
                replace(
                    row,
                    runtime_state=ModelRuntimeState.ERROR,
                    detail="desired state disappeared during startup",
                )
                for row in rows
            )

    catalog = Catalog()
    runtime = DesiredLossRuntime(catalog)
    scheduler = Scheduler()
    endpoints = Endpoints()
    compute_guards = ComputeGuards()
    endpoint_guards = EndpointGuards()
    pool = LocalModelReplicaPoolRuntime(
        deployment_catalog=catalog,
        deployment_runtime=runtime,
        fleet=LosingDesiredFleet(catalog),
        compute_scheduler=scheduler,
        endpoint_allocations=endpoints,
        compute_lease_guards=compute_guards,
        endpoint_lease_guards=endpoint_guards,
    )

    with pytest.raises(
        ExceptionGroup,
        match="creation failed with pending cleanup",
    ) as raised:
        pool.ensure(
            ModelReplicaPoolRequest(
                pool_id="desired-loss-does-not-prove-stop",
                scope=PLATFORM_SCOPE,
                model_id="qwen3-8b",
                engine="vllm",
                python_environment_id="vllm",
                cwd=Path(tmp_path),
                compute=ComputeRequirement(
                    cpu_cores=2,
                    memory_bytes=1024,
                    gpu_count=1,
                    minimum_gpu_memory_bytes=40 * 1024**3,
                ),
                replica_count=1,
            )
        )
    assert "applied generation still physically uncertain" in str(raised.value)
    assert pool.pending_cleanup_count == 1
    assert scheduler.released == []
    assert endpoints.released == []
    assert compute_guards.created[0].closed is False
    assert endpoint_guards.created[0].closed is False

    runtime.applied_uncertain = False
    pool.close_all()

    assert pool.pending_cleanup_count == 0
    assert len(scheduler.released) == 1
    assert len(endpoints.released) == 1
    assert compute_guards.created[0].closed is True
    assert endpoint_guards.created[0].closed is True


def test_model_replica_pool_cleanup_is_retryable_and_never_releases_resources_under_live_service(
    tmp_path,
) -> None:
    class FailOnceRuntime(Runtime):
        def __init__(self, catalog):
            super().__init__(catalog)
            self.failed = False

        def remove_deployment(self, generation):
            if not self.failed:
                self.failed = True
                raise RuntimeError("service stop not yet proven")
            return super().remove_deployment(generation)

    catalog = Catalog()
    runtime = FailOnceRuntime(catalog)
    scheduler = Scheduler()
    endpoints = Endpoints()
    compute_guards = ComputeGuards()
    endpoint_guards = EndpointGuards()
    pool = LocalModelReplicaPoolRuntime(
        deployment_catalog=catalog,
        deployment_runtime=runtime,
        fleet=Fleet(catalog),
        compute_scheduler=scheduler,
        endpoint_allocations=endpoints,
        compute_lease_guards=compute_guards,
        endpoint_lease_guards=endpoint_guards,
    )
    lease = pool.ensure(
        ModelReplicaPoolRequest(
            pool_id="retry-close",
            scope=PLATFORM_SCOPE,
            model_id="qwen3-8b",
            engine="vllm",
            python_environment_id="vllm",
            cwd=Path(tmp_path),
            compute=ComputeRequirement(
                cpu_cores=2,
                memory_bytes=1024,
                gpu_count=1,
                minimum_gpu_memory_bytes=40 * 1024**3,
            ),
        )
    )

    try:
        lease.close()
    except ExceptionGroup as error:
        assert any(
            isinstance(item, RuntimeError)
            and "service stop not yet proven" in str(item)
            for item in error.exceptions
        )
    else:
        raise AssertionError("unproven service shutdown must block resource release")

    assert scheduler.released == []
    assert endpoints.released == []
    assert compute_guards.created[0].closed is False
    assert endpoint_guards.created[0].closed is False

    lease.close()
    assert len(scheduler.released) == 2
    assert len(endpoints.released) == 2
    assert compute_guards.created[0].closed is True
    assert endpoint_guards.created[0].closed is True


def test_concurrent_lease_close_and_pool_close_all_do_not_deadlock(
    tmp_path,
) -> None:
    class BlockingRuntime(Runtime):
        def __init__(self, catalog):
            super().__init__(catalog)
            self.remove_entered = threading.Event()
            self.allow_remove = threading.Event()

        def remove_deployment(self, generation):
            self.remove_entered.set()
            if not self.allow_remove.wait(timeout=5.0):
                raise RuntimeError("timed out waiting to release model teardown")
            return super().remove_deployment(generation)

    catalog = Catalog()
    runtime = BlockingRuntime(catalog)
    scheduler = Scheduler()
    endpoints = Endpoints()
    pool = LocalModelReplicaPoolRuntime(
        deployment_catalog=catalog,
        deployment_runtime=runtime,
        fleet=Fleet(catalog),
        compute_scheduler=scheduler,
        endpoint_allocations=endpoints,
        compute_lease_guards=ComputeGuards(),
        endpoint_lease_guards=EndpointGuards(),
    )
    lease = pool.ensure(
        ModelReplicaPoolRequest(
            pool_id="concurrent-close",
            scope=PLATFORM_SCOPE,
            model_id="qwen3-8b",
            engine="vllm",
            python_environment_id="vllm",
            cwd=Path(tmp_path),
            compute=ComputeRequirement(
                cpu_cores=2,
                memory_bytes=1024,
                gpu_count=1,
                minimum_gpu_memory_bytes=40 * 1024**3,
            ),
            replica_count=1,
        )
    )

    original_close = lease.close
    pool_close_entered_lease = threading.Event()
    errors: list[BaseException] = []

    def observed_close() -> None:
        if threading.current_thread().name == "pool-close-all":
            pool_close_entered_lease.set()
        original_close()

    lease.close = observed_close

    def close_lease() -> None:
        try:
            original_close()
        except BaseException as exc:
            errors.append(exc)

    def close_pool() -> None:
        try:
            pool.close_all()
        except BaseException as exc:
            errors.append(exc)

    lease_thread = threading.Thread(
        target=close_lease,
        name="external-lease-close",
        daemon=True,
    )
    pool_thread = threading.Thread(
        target=close_pool,
        name="pool-close-all",
        daemon=True,
    )
    lease_thread.start()
    assert runtime.remove_entered.wait(timeout=2.0)

    pool_thread.start()
    assert pool_close_entered_lease.wait(timeout=2.0)
    runtime.allow_remove.set()

    lease_thread.join(timeout=3.0)
    pool_thread.join(timeout=3.0)

    assert not lease_thread.is_alive(), "external lease close deadlocked"
    assert not pool_thread.is_alive(), "pool close_all deadlocked"
    assert errors == []
    assert pool.active_lease_count == 0
    assert len(scheduler.released) == 1
    assert len(endpoints.released) == 1


def test_model_replica_pool_runtime_retires_forgotten_active_lease(tmp_path) -> None:
    catalog = Catalog()
    runtime = Runtime(catalog)
    scheduler = Scheduler()
    endpoints = Endpoints()
    compute_guards = ComputeGuards()
    endpoint_guards = EndpointGuards()
    pool = LocalModelReplicaPoolRuntime(
        deployment_catalog=catalog,
        deployment_runtime=runtime,
        fleet=Fleet(catalog),
        compute_scheduler=scheduler,
        endpoint_allocations=endpoints,
        compute_lease_guards=compute_guards,
        endpoint_lease_guards=endpoint_guards,
    )

    pool.ensure(
        ModelReplicaPoolRequest(
            pool_id="forgotten",
            scope=PLATFORM_SCOPE,
            model_id="qwen3-8b",
            engine="vllm",
            python_environment_id="vllm",
            cwd=Path(tmp_path),
            compute=ComputeRequirement(
                cpu_cores=2,
                memory_bytes=1024,
                gpu_count=1,
                minimum_gpu_memory_bytes=40 * 1024**3,
            ),
        )
    )
    assert pool.active_lease_count == 1

    pool.close_all()

    assert pool.active_lease_count == 0
    assert len(runtime.removed) == 2
    assert len(scheduler.released) == 2
    assert len(endpoints.released) == 2
    assert compute_guards.created[0].closed is True
    assert endpoint_guards.created[0].closed is True


def test_model_replica_pool_runtime_close_all_is_retryable_and_seals_new_ensure(
    tmp_path,
) -> None:
    class FailOnceRuntime(Runtime):
        def __init__(self, catalog):
            super().__init__(catalog)
            self.failed = False

        def remove_deployment(self, generation):
            if not self.failed:
                self.failed = True
                raise RuntimeError("simulated model stop uncertainty")
            return super().remove_deployment(generation)

    catalog = Catalog()
    runtime = FailOnceRuntime(catalog)
    scheduler = Scheduler()
    endpoints = Endpoints()
    pool = LocalModelReplicaPoolRuntime(
        deployment_catalog=catalog,
        deployment_runtime=runtime,
        fleet=Fleet(catalog),
        compute_scheduler=scheduler,
        endpoint_allocations=endpoints,
        compute_lease_guards=ComputeGuards(),
        endpoint_lease_guards=EndpointGuards(),
    )
    request = ModelReplicaPoolRequest(
        pool_id="retry-runtime-close",
        scope=PLATFORM_SCOPE,
        model_id="qwen3-8b",
        engine="vllm",
        python_environment_id="vllm",
        cwd=Path(tmp_path),
        compute=ComputeRequirement(
            cpu_cores=2,
            memory_bytes=1024,
            gpu_count=1,
            minimum_gpu_memory_bytes=40 * 1024**3,
        ),
    )
    pool.ensure(request)

    try:
        pool.close_all()
    except ExceptionGroup as error:
        assert any(
            "simulated model stop uncertainty" in message
            for message in _exception_leaf_messages(error)
        )
    else:
        raise AssertionError("uncertain model stop must keep pool cleanup retryable")

    assert pool.active_lease_count == 1
    try:
        pool.ensure(request)
    except RuntimeError as error:
        assert "closing" in str(error)
    else:
        raise AssertionError("closing replica pool must reject new ensure")

    pool.close_all()
    assert pool.active_lease_count == 0
