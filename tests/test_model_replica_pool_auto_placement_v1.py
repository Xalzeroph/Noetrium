from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from noetrium_platform.capabilities.model.deployment.api import (
    ModelDeploymentGeneration,
    ModelDesiredDeployment,
    ModelDeploymentStatus,
    ModelDesiredState,
    ModelRuntimeState,
)
from noetrium_platform.capabilities.model.deployment.composition import (
    LocalModelReplicaPoolRuntime,
    ModelReplicaPoolRequest,
)
from noetrium_platform.capabilities.model.deployment.composition.replica_pool import (
    _dominated_warm_runtime_identities,
    _warm_runtime_capability,
)
from noetrium_platform.capabilities.model.stack.api import (
    ModelArtifactClosure,
    FrozenModelStack,
    RuntimeBuildIdentity,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.kernel.identity import ImmutableModelIdentity
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE
from noetrium_platform.infrastructure.resources.allocation.api import (
    EndpointProbeResult,
)
from noetrium_platform.infrastructure.resources.authority import (
    LeaseHeartbeatFactory,
    UniversalResourceAuthority,
)
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeGPU,
    ComputeHost,
    ComputeRequirement,
    GpuDeviceStatus,
    GpuRuntimeSnapshot,
    HostRuntimeSnapshot,
)


def _stack() -> FrozenModelStack:
    return FrozenModelStack(
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
            "c" * 64,
            "engine",
            "lock",
            "cuda",
            "nccl",
            "torch",
            "kernels",
        ),
        1,
        1,
        1,
        1,
        None,
        None,
        None,
        None,
        "fcfs",
    )


class Catalog:
    def __init__(self) -> None:
        self.rows = {}

    def put_deployment(self, spec):
        existing = self.rows.get(spec.deployment_id)
        if existing is not None and canonical_digest(existing) != canonical_digest(spec):
            raise RuntimeError("deployment identity drift")
        self.rows[spec.deployment_id] = spec
        return spec

    def deployment(self, deployment_id):
        return self.rows[deployment_id]

    def deployments(self):
        return tuple(self.rows[key] for key in sorted(self.rows))


class Runtime:
    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog
        self.running: set[str] = set()
        self.starts: list[str] = []
        self.removed: list[str] = []

    def generation(self, deployment_id):
        spec = self.catalog.rows[deployment_id]
        applied = (
            canonical_digest({"applied": deployment_id})
            if deployment_id in self.running
            else None
        )
        return ModelDeploymentGeneration(
            deployment_id,
            canonical_digest(spec),
            applied,
        )

    def start(self, generation):
        current = self.generation(generation.deployment_id)
        if current.desired_deployment_digest != generation.desired_deployment_digest:
            raise RuntimeError("stale desired generation")
        self.running.add(generation.deployment_id)
        self.starts.append(generation.deployment_id)
        return self.status(generation.deployment_id)

    def recover_applied(self, generation):
        current = self.generation(generation.deployment_id)
        if current.desired_deployment_digest != generation.desired_deployment_digest:
            raise RuntimeError("stale desired generation")
        if current.applied_runtime_digest is None:
            raise RuntimeError("mock deployment is not physically running")
        return current

    def status(self, deployment_id):
        spec = self.catalog.rows[deployment_id]
        running = deployment_id in self.running
        return ModelDeploymentStatus(
            deployment_id,
            spec.service_id,
            spec.desired_state,
            ModelRuntimeState.RUNNING if running else ModelRuntimeState.STOPPED,
            1001 if running else None,
            "ready" if running else "stopped",
        )

    def remove_deployment(self, generation):
        current = self.generation(generation.deployment_id)
        if current.desired_deployment_digest != generation.desired_deployment_digest:
            raise RuntimeError("stale removal generation")
        self.running.discard(generation.deployment_id)
        self.removed.append(generation.deployment_id)
        self.catalog.rows.pop(generation.deployment_id, None)
        return True


class Inventory:
    def __init__(self) -> None:
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

    def list_hosts(self, *, scope=None):
        if scope is not None and scope != self.host.scope:
            return ()
        return (self.host,)


class CandidatePorts:
    def candidate_ports(self, *, host, count, protocol):
        del host, protocol
        return tuple(range(18000, 18000 + count))


class Probe:
    def probe(self, endpoint):
        return EndpointProbeResult(endpoint, True, "free")


class GpuObserver:
    def snapshot(self):
        return GpuRuntimeSnapshot(
            True,
            devices=(
                GpuDeviceStatus("0", "GPU-a", "GPU", 49152, 0, 49152, 0),
                GpuDeviceStatus("1", "GPU-b", "GPU", 49152, 0, 49152, 0),
            ),
            processes=(),
            processes_complete=True,
        )


class HostObserver:
    def snapshot(self):
        return HostRuntimeSnapshot(False, detail="not-required")


class _TestLeaseHeartbeatGuard:
    def start(self) -> None:
        return None

    def assert_healthy(self) -> None:
        return None

    def close(self) -> None:
        return None


class _TestLeaseHeartbeatFactory(LeaseHeartbeatFactory):
    """Short-lived unit-test factory; Authority TTL truth is still real."""

    def __init__(self) -> None:
        pass

    def create(self, rows):
        assert rows
        return _TestLeaseHeartbeatGuard()

    def close(self) -> None:
        return None


def _request(tmp_path: Path) -> ModelReplicaPoolRequest:
    return ModelReplicaPoolRequest(
        pool_id="qwen-pool",
        scope=PLATFORM_SCOPE,
        model_id="qwen3-8b",
        engine="vllm",
        cwd=tmp_path / "runtime",
        compute=ComputeRequirement(
            cpu_cores=2,
            memory_bytes=1024,
            gpu_count=1,
            minimum_gpu_memory_bytes=40 * 1024**3,
        ),
        model_stack=_stack(),
        replica_count=1,
    )


def _pool(tmp_path: Path, authority, catalog, runtime):
    return LocalModelReplicaPoolRuntime(
        deployment_catalog=catalog,
        deployment_runtime=runtime,
        resource_authority=authority,
        compute_inventory=Inventory(),
        endpoint_candidates=CandidatePorts(),
        endpoint_probe=Probe(),
        gpu_runtime_observer=GpuObserver(),
        host_runtime_observer=HostObserver(),
        consumer_lease_guard_factory=_TestLeaseHeartbeatFactory(),
        consumer_holder_id="model-replica-test-consumer",
    )


def test_replica_pool_materializes_one_authority_closure(tmp_path: Path) -> None:
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    catalog = Catalog()
    runtime = Runtime(catalog)
    pool = _pool(tmp_path, authority, catalog, runtime)
    lease = pool.ensure(_request(tmp_path))
    row = lease.report.placements[0]

    snapshot = authority.snapshot()
    assert snapshot.binding_for(row.service_resource_key) is not None
    assert len(snapshot.current_claims_for(row.compute_resource_key)) == 1
    assert len(snapshot.current_claims_for(row.endpoint_resource_key)) == 1
    assert len(snapshot.current_claims_for(row.service_resource_key)) == 1
    assert row.gpu_ids == ("GPU-a",)
    assert row.endpoint_port == 18000
    assert runtime.starts == [row.deployment_id]
    lease.assert_healthy()



def test_cross_pool_retirement_is_fenced_by_live_consumer(tmp_path: Path) -> None:
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    catalog = Catalog()
    runtime = Runtime(catalog)
    request = _request(tmp_path)

    first = _pool(tmp_path, authority, catalog, runtime)
    first_lease = first.ensure(request)
    deployment_id = first_lease.report.placements[0].deployment_id

    second = _pool(tmp_path, authority, catalog, runtime)
    second_lease = second.ensure(request)
    assert second_lease.report.placements[0].deployment_id == deployment_id
    second_lease.close()

    try:
        second.close_all()
    except BaseExceptionGroup as exc:
        assert any(
            "active consumers" in str(child) for child in exc.exceptions
        )
    else:
        raise AssertionError("cross-pool retirement bypassed a live consumer")

    assert deployment_id in runtime.running
    assert deployment_id not in runtime.removed
    snapshot = authority.snapshot_for_holder(
        "model-runtime:" + request.runtime_identity_digest
    )
    assert any(
        dict(row.attributes.get("attributes", {})).get("kind") == "model-service"
        for row in snapshot.claims
    )

    first_lease.close()
    first.detach_all()
    second.close_all()
    assert deployment_id not in runtime.running
    assert deployment_id in runtime.removed


def test_same_runtime_identity_has_one_warm_owner_under_concurrency(tmp_path: Path) -> None:
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    catalog = Catalog()
    runtime = Runtime(catalog)
    pool = _pool(tmp_path, authority, catalog, runtime)
    request = _request(tmp_path)

    with ThreadPoolExecutor(max_workers=8) as executor:
        leases = tuple(executor.map(lambda _: pool.ensure(request), range(16)))
    ids = {lease.report.placements[0].deployment_id for lease in leases}
    assert len(ids) == 1
    assert pool.warm_owner_count == 1
    assert pool.active_lease_count == 16
    assert len(runtime.starts) == 1
    for lease in leases:
        lease.close()
    assert pool.active_lease_count == 0
    assert pool.warm_owner_count == 1


def test_controller_restart_adopts_exact_authority_realization(tmp_path: Path) -> None:
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    catalog = Catalog()
    runtime = Runtime(catalog)
    request = _request(tmp_path)

    first = _pool(tmp_path, authority, catalog, runtime)
    lease = first.ensure(request)
    deployment_id = lease.report.placements[0].deployment_id
    lease.close()
    first.detach_all()
    assert deployment_id in runtime.running

    restarted = _pool(tmp_path, authority, catalog, runtime)
    adopted = restarted.ensure(request)
    assert adopted.report.placements[0].deployment_id == deployment_id
    assert runtime.starts.count(deployment_id) >= 1
    adopted.close()
    restarted.close_all()
    assert deployment_id in runtime.removed
    assert deployment_id not in runtime.running
    assert authority.snapshot().claims == ()


def _warm_spec(
    tmp_path: Path,
    *,
    deployment_id: str,
    context_length: int,
    max_num_seqs: int | None = None,
    gpu_devices: tuple[str, ...] = ("GPU-a",),
) -> ModelDesiredDeployment:
    args = [
        "/usr/local/bin/vllm",
        "serve",
        "/model",
        "--max-model-len",
        str(context_length),
    ]
    if max_num_seqs is not None:
        args.extend(("--max-num-seqs", str(max_num_seqs)))
    return ModelDesiredDeployment(
        deployment_id=deployment_id,
        scope=PLATFORM_SCOPE,
        service_id="model:" + deployment_id,
        model_id="qwen3-8b",
        engine="vllm",
        container_digest="c" * 64,
        executable="/usr/local/bin/vllm",
        argv=tuple(args),
        cwd=tmp_path,
        gpu_devices=gpu_devices,
        gpu_memory_reservation_bytes=tuple(
            8 * 1024**3 for _ in gpu_devices
        ),
        desired_state=ModelDesiredState.RUNNING,
    )


def test_warm_context_dominance_requires_identical_runtime_admission(tmp_path: Path) -> None:
    weak = _warm_runtime_capability(
        _warm_spec(
            tmp_path,
            deployment_id="weak",
            context_length=12041,
        )
    )
    strong = _warm_runtime_capability(
        _warm_spec(
            tmp_path,
            deployment_id="strong",
            context_length=39145,
        )
    )
    tuned = _warm_runtime_capability(
        _warm_spec(
            tmp_path,
            deployment_id="tuned",
            context_length=40960,
            max_num_seqs=352,
        )
    )
    tp2 = _warm_runtime_capability(
        _warm_spec(
            tmp_path,
            deployment_id="tp2",
            context_length=40960,
            gpu_devices=("GPU-a", "GPU-b"),
        )
    )
    assert weak is not None
    assert strong is not None
    assert tuned is not None
    assert tp2 is not None
    assert strong.strictly_dominates(weak)
    assert not weak.strictly_dominates(strong)
    assert not tuned.strictly_dominates(strong)
    assert not strong.strictly_dominates(tuned)
    assert not tp2.strictly_dominates(strong)


def test_warm_reclaim_marks_only_semantically_dominated_reclaimable_identity(
    tmp_path: Path,
) -> None:
    weak = _warm_runtime_capability(
        _warm_spec(
            tmp_path,
            deployment_id="weak",
            context_length=12041,
        )
    )
    strong = _warm_runtime_capability(
        _warm_spec(
            tmp_path,
            deployment_id="strong",
            context_length=39145,
        )
    )
    tuned = _warm_runtime_capability(
        _warm_spec(
            tmp_path,
            deployment_id="tuned",
            context_length=40960,
            max_num_seqs=352,
        )
    )
    assert weak is not None and strong is not None and tuned is not None
    capabilities = {
        "weak": weak,
        "strong": strong,
        "tuned": tuned,
    }
    assert _dominated_warm_runtime_identities(
        capabilities,
        reclaimable=frozenset({"weak", "strong", "tuned"}),
    ) == frozenset({"weak"})
    # A protected/non-reclaimable strong runtime may still safely prove that a
    # weak reclaimable runtime is redundant.
    assert _dominated_warm_runtime_identities(
        capabilities,
        reclaimable=frozenset({"weak"}),
    ) == frozenset({"weak"})


def test_dominance_gc_retires_unleased_weaker_warm_owner(tmp_path: Path) -> None:
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    catalog = Catalog()
    runtime = Runtime(catalog)
    pool = _pool(tmp_path, authority, catalog, runtime)
    pool._exclusive_runtime_fabric_consumer = lambda: True

    base = _stack()
    weak_stack = replace(
        base,
        identity=replace(base.identity, context_length=12041),
    )
    strong_stack = replace(
        base,
        identity=replace(base.identity, context_length=39145),
    )

    def request(pool_id: str, stack: FrozenModelStack) -> ModelReplicaPoolRequest:
        return ModelReplicaPoolRequest(
            pool_id=pool_id,
            scope=PLATFORM_SCOPE,
            model_id="qwen3-8b",
            engine="vllm",
            cwd=tmp_path / "runtime",
            compute=ComputeRequirement(
                cpu_cores=2,
                memory_bytes=1024,
                gpu_count=1,
                minimum_gpu_memory_bytes=40 * 1024**3,
            ),
            model_stack=stack,
            replica_count=1,
        )

    weak_request = request("weak", weak_stack)
    strong_request = request("strong", strong_stack)

    weak_lease = pool.ensure(weak_request)
    weak_deployment = weak_lease.report.placements[0].deployment_id
    weak_lease.close()

    strong_lease = pool.ensure(strong_request)
    strong_deployment = strong_lease.report.placements[0].deployment_id
    strong_lease.assert_healthy()

    retired = pool.reclaim_dominated_warm_realizations()

    assert retired == (weak_request.runtime_identity_digest,)
    assert weak_deployment in runtime.removed
    assert strong_deployment not in runtime.removed
    assert pool.warm_owner_count == 1
    strong_lease.assert_healthy()

    strong_lease.close()
    pool.close_all()


def test_warm_dominance_detection_does_not_use_pairwise_comparisons(
    tmp_path: Path,
    monkeypatch,
) -> None:
    weak = _warm_runtime_capability(
        _warm_spec(
            tmp_path,
            deployment_id="weak-linear",
            context_length=12041,
        )
    )
    strong = _warm_runtime_capability(
        _warm_spec(
            tmp_path,
            deployment_id="strong-linear",
            context_length=39145,
        )
    )
    assert weak is not None and strong is not None

    def forbidden_pairwise(*_args, **_kwargs):
        raise AssertionError("pairwise warm dominance scan is forbidden")

    monkeypatch.setattr(
        type(weak),
        "strictly_dominates",
        forbidden_pairwise,
    )
    assert _dominated_warm_runtime_identities(
        {"weak": weak, "strong": strong},
        reclaimable=frozenset({"weak", "strong"}),
    ) == frozenset({"weak"})


def test_consumer_admission_precedes_model_materialization_and_fences_retirement(
    tmp_path: Path,
) -> None:
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    catalog = Catalog()
    runtime = Runtime(catalog)
    pool = _pool(tmp_path, authority, catalog, runtime)
    request = _request(tmp_path)
    original = pool._materialize_owner
    key = pool._consumer_resource_key(request.runtime_identity_digest)

    def during_materialization(value):
        leases = authority.active_leases(key)
        assert len(leases) == 1
        try:
            authority.fence_if_no_live_leases(
                key, holder_key="competing-process-retirement",
            )
        except RuntimeError as exc:
            assert "resource generation still has live consumers:" in str(exc)
        else:
            raise AssertionError("model was exposed to zero-consumer retirement")
        return original(value)

    pool._materialize_owner = during_materialization
    lease = pool.ensure(request)
    assert len(authority.active_leases(key)) == 1
    assert pool.active_lease_count == 1
    lease.close()
    assert authority.active_leases(key) == ()
    pool.close_all()


def test_failed_model_materialization_releases_early_consumer_admission(
    tmp_path: Path,
) -> None:
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    pool = _pool(tmp_path, authority, Catalog(), Runtime(Catalog()))
    request = _request(tmp_path)
    key = pool._consumer_resource_key(request.runtime_identity_digest)

    def interrupted(_request):
        assert len(authority.active_leases(key)) == 1
        raise RuntimeError("simulated model materialization failure")

    pool._materialize_owner = interrupted
    try:
        pool.ensure(request)
    except RuntimeError as exc:
        assert str(exc) == "simulated model materialization failure"
    else:
        raise AssertionError("the materialization failure was swallowed")
    assert authority.active_leases(key) == ()
    assert pool.active_lease_count == 0
    assert pool.warm_owner_count == 0


def test_failed_model_attachment_cannot_retire_new_foreign_consumer(
    tmp_path: Path,
) -> None:
    authority = UniversalResourceAuthority(tmp_path / "authority.sqlite")
    catalog = Catalog()
    runtime = Runtime(catalog)
    pool = _pool(tmp_path, authority, catalog, runtime)
    request = _request(tmp_path)
    key = pool._consumer_resource_key(request.runtime_identity_digest)
    calls = []
    foreign = []

    def competing_reconcile(*args, **kwargs):
        calls.append(kwargs)
        foreign.append(authority.acquire_ttl_lease(
            lease_id="foreign-model-consumer",
            resource_key=key,
            holder_key="other-control-process",
            owner_scope=PLATFORM_SCOPE,
            ttl_seconds=60.0,
        ))
        raise RuntimeError("simulated parallel model attachment conflict")

    authority.reconcile = competing_reconcile
    try:
        pool.ensure(request)
    except RuntimeError as exc:
        assert str(exc) == "simulated parallel model attachment conflict"
    else:
        raise AssertionError("original producer failure was swallowed")
    # A competing producer admitted after our initial Authority snapshot.
    # No compensating reconcile with empty desired resources may erase it.
    assert len(calls) == 1
    assert len(authority.active_leases(key)) == 1
    authority.release_lease(foreign[0])
    assert authority.active_leases(key) == ()
