from __future__ import annotations

from dataclasses import replace
from pathlib import Path

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
        if self.next >= 2:
            raise ComputePlacementUnavailable(requirement)
        gpu = self.host.gpus[self.next]
        self.next += 1
        return ComputeAllocation(
            allocation_id,
            scope,
            self.host.host_id,
            requirement.cpu_cores,
            requirement.memory_bytes,
            (gpu.gpu_id,),
            self.next,
            9999999999.0,
        )

    def release(self, allocation):
        self.released.append(allocation.allocation_id)


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

    def release(self, allocation):
        self.released.append(allocation.allocation_id)
        current = self.rows[allocation.allocation_id]
        if current.lease_fencing_token != allocation.lease_fencing_token:
            raise RuntimeError("stale endpoint allocation generation")
        released = replace(current, state=EndpointAllocationState.RELEASED)
        self.rows[allocation.allocation_id] = released
        return released


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
            "simulated model stop uncertainty" in str(item)
            for item in error.exceptions
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
