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
)


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
    assert "simulated startup failure" in str(raised.value)
    assert "simulated creation cleanup failure" in str(raised.value)
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
