from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event, Lock
import time

import pytest

from noetrium_platform.capabilities.model.api import (
    ModelCapabilityRequirement,
    ModelProviderProfile,
)
from noetrium_platform.capabilities.model.providers.project import QualifiedModelProjectProvider
from noetrium_platform.capabilities.model.request.api import ModelRequestEnvelope
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointError,
    ModelEndpointResponse,
    ModelEndpointRoute,
    OperationalModelEndpointReplica,
    ModelEndpointReplicaSet,
    QualifiedModelEndpointBinding,
    ModelEndpointReplicaSet,
    ModelRuntimePressureSnapshot,
)
from noetrium_platform.capabilities.model.serving.endpoint.runtime import (
    AdaptiveModelEndpointPool,
    PinnedReplicaSelectionPolicy,
)
from noetrium_platform.capabilities.model.serving.endpoint.runtime.replica_pool import (
    _request_prefix_affinity_keys,
)
from noetrium_platform.evidence.artifact.content.api import ArtifactBlobRef
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    ImmutableModelIdentity,
    canonical_bytes,
    canonical_digest,
)
from tests._model_tokenization_support import FixedModelRequestTokenizationProvider


def _model() -> ImmutableModelIdentity:
    return ImmutableModelIdentity(
        "qwen3-8b",
        "Qwen3-8B",
        "a" * 64,
        "vllm",
        "0.8.5",
        "bfloat16",
        None,
        8192,
        "b" * 64,
    )


def _binding(index: int, *, capacity: int = 2) -> QualifiedModelEndpointBinding:
    return QualifiedModelEndpointBinding(
        role="reasoner",
        capability_id="generation",
        input_schema_id="model.generation.request.v1",
        output_schema_id="model.generation.response.v1",
        deployment_id=f"replica-{index}",
        deployment_generation=f"{index + 1:064x}",
        base_url=f"http://127.0.0.1:{18000 + index}",
        model=_model(),
        model_stack_digest="c" * 64,
        qualification_certificate_digest=f"{100 + index:064x}",
        runtime_qualification_digest=f"{200 + index:064x}",
        host_identity_digest="d" * 64,
        prompt_generation="prompt-v1",
        max_admitted_concurrency=capacity,
        runtime_canary_evidence_digests=(f"{300 + index:064x}",),
        tokenizer_sha256="e" * 64,
        chat_template_sha256="f" * 64,
        verified_capabilities=("generation","chat"),
    )


def _envelope(index: int = 0) -> ModelRequestEnvelope:
    body = canonical_bytes({"model": "qwen", "messages": [{"role": "user", "content": "x"}]})
    return ModelRequestEnvelope(
        schema_version="model-request.v1",
        request_id=f"request-{index}",
        context=ExecutionContext(f"run-{index}", f"trace-{index}", f"span-{index}"),
        role="reasoner",
        model=_model(),
        prompt_generation_id="prompt-v1",
        prompt_id="prompt",
        prompt_digest="1" * 64,
        request_body=ArtifactBlobRef(canonical_digest({"body": index}), len(body), "application/json"),
    )


class _GateEndpoint:
    def __init__(self, binding, gate: Event, entered: list[str], lock: Lock) -> None:
        self._route = (
            binding.route
            if isinstance(binding, OperationalModelEndpointReplica)
            else ModelEndpointRoute(
                binding.deployment_id,
                binding.deployment_generation,
                binding.base_url,
            )
        )
        self._gate = gate
        self._entered = entered
        self._lock = lock

    @property
    def route(self):
        return self._route

    def complete(self, request):
        with self._lock:
            self._entered.append(request.deployment_id)
        if not self._gate.wait(5):
            raise TimeoutError("test gate did not open")
        return ModelEndpointResponse(
            request_id=request.request.request_id,
            deployment_id=request.deployment_id,
            text="ok",
        )


def _owned_envelope(owner_id: str, index: int) -> ModelRequestEnvelope:
    body = canonical_bytes(
        {"model": "qwen", "messages": [{"role": "user", "content": "x"}]}
    )
    return ModelRequestEnvelope(
        schema_version="model-request.v1",
        request_id=f"owned-request-{owner_id}-{index}",
        context=ExecutionContext(
            f"run-{owner_id}-{index}",
            f"trace-{owner_id}-{index}",
            f"span-{owner_id}-{index}",
            study_id=owner_id,
        ),
        role="reasoner",
        model=_model(),
        prompt_generation_id="prompt-v1",
        prompt_id="prompt",
        prompt_digest="1" * 64,
        request_body=ArtifactBlobRef(
            canonical_digest({"owner": owner_id, "body": index}),
            len(body),
            "application/json",
        ),
    )


class _OwnerGateEndpoint:
    def __init__(self, binding, gate: Event, entered: list[str], lock: Lock) -> None:
        self._route = ModelEndpointRoute(
            binding.deployment_id,
            binding.deployment_generation,
            binding.base_url,
        )
        self._gate = gate
        self._entered = entered
        self._lock = lock

    @property
    def route(self):
        return self._route

    def complete(self, request):
        owner = request.request.context.study_id or request.request.context.run_id
        with self._lock:
            self._entered.append(owner)
        if not self._gate.wait(5):
            raise TimeoutError("owner fairness test gate did not open")
        return ModelEndpointResponse(
            request_id=request.request.request_id,
            deployment_id=request.deployment_id,
            text="ok",
        )


class _CapacityEndpoint:
    def __init__(self, binding) -> None:
        self._route = ModelEndpointRoute(
            binding.deployment_id,
            binding.deployment_generation,
            binding.base_url,
        )

    @property
    def route(self):
        return self._route

    def complete(self, request):
        raise ModelEndpointError(
            "replica is overloaded",
            failure_kind="capacity",
            retryable=True,
            affects_replica_health=False,
        )


class _FailingEndpoint:
    def __init__(self, binding, fail: bool) -> None:
        self._route = (
            binding.route
            if isinstance(binding, OperationalModelEndpointReplica)
            else ModelEndpointRoute(
                binding.deployment_id,
                binding.deployment_generation,
                binding.base_url,
            )
        )
        self._fail = fail
        self.calls = 0

    @property
    def route(self):
        return self._route

    def complete(self, request):
        self.calls += 1
        if self._fail:
            raise RuntimeError("replica failed")
        return ModelEndpointResponse(
            request_id=request.request.request_id,
            deployment_id=request.deployment_id,
            text="ok",
        )


def test_single_replica_skips_prefix_affinity_bookkeeping() -> None:
    binding = _binding(0, capacity=2)
    pool = AdaptiveModelEndpointPool(
        ModelEndpointReplicaSet((binding,)),
        lambda row: _FailingEndpoint(row, False),
    )
    body = {
        "model": "qwen",
        "messages": [
            {"role": "system", "content": "stable system prefix"},
            *(
                {"role": "user", "content": f"turn-{index}"}
                for index in range(40)
            ),
        ],
    }
    result = pool.complete(_envelope(0), body)
    assert result.response.text == "ok"
    snapshot = pool.snapshot()
    assert snapshot.replicas[0].prefix_affinity_entries == 0
    assert snapshot.replicas[0].prefix_affinity_selections == 0


def test_replica_set_rejects_scientific_model_drift() -> None:
    first = _binding(0)
    second = _binding(1)
    drifted = QualifiedModelEndpointBinding(
        role=second.role,
        capability_id="generation",
        input_schema_id="model.generation.request.v1",
        output_schema_id="model.generation.response.v1",
        deployment_id=second.deployment_id,
        deployment_generation=second.deployment_generation,
        base_url=second.base_url,
        model=ImmutableModelIdentity(
            "other", "Other", "a" * 64, "vllm", "0.8.5",
            "bfloat16", None, 8192, "b" * 64,
        ),
        model_stack_digest=second.model_stack_digest,
        qualification_certificate_digest=second.qualification_certificate_digest,
        runtime_qualification_digest=second.runtime_qualification_digest,
        host_identity_digest=second.host_identity_digest,
        prompt_generation=second.prompt_generation,
        max_admitted_concurrency=second.max_admitted_concurrency,
        runtime_canary_evidence_digests=second.runtime_canary_evidence_digests,
        tokenizer_sha256=second.tokenizer_sha256,
        chat_template_sha256=second.chat_template_sha256,
    )
    with pytest.raises(ValueError, match="same immutable model"):
        ModelEndpointReplicaSet((first, drifted))


def test_stale_runtime_pressure_cannot_permanently_starve_replica() -> None:
    clock = [0.0]
    bindings = (_binding(0, capacity=2), _binding(1, capacity=2))
    pool = AdaptiveModelEndpointPool(
        ModelEndpointReplicaSet(bindings),
        _CapacityEndpoint,
        pressure_probe_interval_seconds=1.0,
        clock=lambda: clock[0],
    )
    pool._runtimes["replica-0"].pressure_snapshot = ModelRuntimePressureSnapshot(
        deployment_id="replica-0",
        observed_monotonic=0.0,
        requests_running=1,
        requests_waiting=4,
        gpu_kv_cache_usage=0.99,
        preemptions_total=0,
    )

    with pool._cv:
        _now, fresh_binding, _runtime, _depth, _cooling = (
            pool._selection_candidate_locked((), frozenset())
        )
    assert fresh_binding.deployment_id == "replica-1"

    clock[0] = 4.0
    with pool._cv:
        _now, stale_binding, _runtime, _depth, _cooling = (
            pool._selection_candidate_locked((), frozenset())
        )
    assert stale_binding.deployment_id == "replica-0"


def test_owner_head_lazy_heap_is_amortized_bounded() -> None:
    pool = AdaptiveModelEndpointPool(
        ModelEndpointReplicaSet((_binding(0, capacity=1),)),
        _CapacityEndpoint,
    )
    with pool._cv:
        waiter = pool._waiters_by_ticket.get(0)
        if waiter is not None:
            raise AssertionError("unexpected preexisting waiter")
        from noetrium_platform.capabilities.model.serving.endpoint.runtime.replica_pool import _PoolWaiter
        waiter = _PoolWaiter(0, "paper-a")
        pool._enqueue_waiter_locked(waiter)
        for sequence in range(2000):
            pool._active_by_owner["paper-a"] = sequence % 3
            pool._owner_last_grant["paper-a"] = sequence
            pool._push_owner_head_locked("paper-a")

        assert len(pool._waiter_owner_heap) <= 64
        assert pool._selected_waiter_locked() is waiter


def test_pool_spreads_parallel_pressure_across_all_qualified_replicas() -> None:
    bindings = tuple(_binding(index, capacity=2) for index in range(4))
    replica_set = ModelEndpointReplicaSet(bindings)
    gate = Event()
    lock = Lock()
    entered: list[str] = []
    endpoints = {}

    def factory(binding):
        endpoint = _GateEndpoint(binding, gate, entered, lock)
        endpoints[binding.deployment_id] = endpoint
        return endpoint

    pool = AdaptiveModelEndpointPool(replica_set, factory)

    def invoke(index: int):
        return pool.complete(
            _envelope(index),
            {"model": "qwen", "messages": ({"role": "user", "content": "x"},)},
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(invoke, index) for index in range(8)]
        deadline = time.monotonic() + 3
        while len(entered) < 8 and time.monotonic() < deadline:
            time.sleep(0.01)
        snapshot = pool.snapshot()
        assert [row.in_flight for row in snapshot.replicas] == [2, 2, 2, 2]
        assert [row.selections for row in snapshot.replicas] == [2, 2, 2, 2]
        gate.set()
        results = [future.result(timeout=3) for future in futures]

    assert {row.response.deployment_id for row in results} == {
        "replica-0", "replica-1", "replica-2", "replica-3"
    }
    final = pool.snapshot()
    assert [row.completed for row in final.replicas] == [2, 2, 2, 2]
    assert [row.in_flight for row in final.replicas] == [0, 0, 0, 0]


def test_pool_quarantines_failed_replica_without_replaying_uncertain_request() -> None:
    bindings = tuple(_binding(index, capacity=1) for index in range(2))
    replica_set = ModelEndpointReplicaSet(bindings)
    endpoints = {}

    def factory(binding):
        endpoint = _FailingEndpoint(binding, fail=binding.deployment_id == "replica-0")
        endpoints[binding.deployment_id] = endpoint
        return endpoint

    pool = AdaptiveModelEndpointPool(
        replica_set,
        factory,
        failure_cooldown_seconds=60,
        max_failure_cooldown_seconds=60,
    )
    with pytest.raises(RuntimeError, match="replica failed"):
        pool.complete(_envelope(0), {"model": "qwen"})
    # The failed request was invoked exactly once and was not replayed.
    assert endpoints["replica-0"].calls == 1
    assert endpoints["replica-1"].calls == 0

    result = pool.complete(_envelope(1), {"model": "qwen"})
    assert result.response.deployment_id == "replica-1"
    snapshot = pool.snapshot()
    first, second = snapshot.replicas
    assert first.failures == 1 and first.cooling_down is True
    assert second.completed == 1


class _RecorderStub:
    durability = "test"

    def record(self, **kwargs):
        raise AssertionError("not used by binding-only test")

    def record_operation(self, **kwargs):
        raise AssertionError("not used by binding-only test")

    def reconstruct(self, envelope):
        raise AssertionError("not used by binding-only test")

    def reconstruct_request_body(self, envelope):
        raise AssertionError("not used by binding-only test")

    def verify_visible_request(self, envelope, actual_body):
        return None


class _ReplicaBindings:
    def __init__(self, replica_set: ModelEndpointReplicaSet) -> None:
        self.replica_set = replica_set

    def binding_for(self, *, role: str, capability_id: str, input_schema_id: str, output_schema_id: str, prompt_generation: str | None = None):
        assert role == self.replica_set.role
        assert prompt_generation == self.replica_set.prompt_generation
        return self.replica_set.members[0]

    def replica_set_for(self, *, role: str, capability_id: str, input_schema_id: str, output_schema_id: str, prompt_generation: str | None = None):
        assert role == self.replica_set.role
        assert prompt_generation == self.replica_set.prompt_generation
        return self.replica_set


def test_project_provider_materializes_replica_pool_instead_of_single_endpoint() -> None:
    replica_set = ModelEndpointReplicaSet((_binding(0), _binding(1)))
    materialized: list[ModelEndpointReplicaSet] = []


    def replica_pool_factory(value: ModelEndpointReplicaSet):
        materialized.append(value)
        return object()

    provider = QualifiedModelProjectProvider(
        ModelProviderProfile("replicated", ("generation","chat")),
        _ReplicaBindings(replica_set),
        replica_pool_factory,
        _RecorderStub(),
        FixedModelRequestTokenizationProvider(),
    )
    requirement = ModelCapabilityRequirement(
        role="reasoner",
        prompt_generation_id="prompt-v1",
        prompt_id="prompt",
        prompt_digest="1" * 64,
        required_capabilities=("chat",),
    )

    client = provider.bind_capability(requirement)

    assert materialized == [replica_set]
    assert client.binding.deployment_id == replica_set.members[0].deployment_id
    assert provider.bind_capability(requirement) is client


def _operational(index: int, *, capacity: int = 2) -> OperationalModelEndpointReplica:
    return OperationalModelEndpointReplica(
        ModelEndpointRoute(
            f"operational-{index}",
            f"{index + 20:064x}",
            f"http://127.0.0.1:{19000 + index}",
        ),
        capacity,
    )


def test_operational_replica_set_binds_route_and_capacity_without_qualification() -> None:
    first = ModelEndpointReplicaSet((_operational(0, capacity=1), _operational(1)))
    second = ModelEndpointReplicaSet((_operational(0, capacity=2), _operational(1)))
    assert first.replica_set_digest != second.replica_set_digest
    assert len(first.replica_set_digest) == 64


def test_operational_pool_spreads_pressure_without_claiming_qualification() -> None:
    replica_set = ModelEndpointReplicaSet(
        tuple(_operational(index, capacity=1) for index in range(2))
    )
    gate = Event()
    lock = Lock()
    entered: list[str] = []
    pool = AdaptiveModelEndpointPool(
        replica_set,
        lambda replica: _GateEndpoint(replica, gate, entered, lock),
    )

    def invoke(index: int):
        return pool.complete(
            _envelope(index),
            {"model": "qwen", "messages": ({"role": "user", "content": "x"},)},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(invoke, index) for index in range(2)]
        deadline = time.monotonic() + 3
        while len(entered) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert set(entered) == {"operational-0", "operational-1"}
        gate.set()
        results = [future.result(timeout=3) for future in futures]
    assert {row.response.deployment_id for row in results} == {
        "operational-0", "operational-1"
    }
    assert pool.snapshot().selection_sequence == 2


def test_operational_pool_does_not_replay_uncertain_failure() -> None:
    replica_set = ModelEndpointReplicaSet((_operational(0), _operational(1)))
    endpoints = {}

    def factory(replica):
        endpoint = _FailingEndpoint(replica, fail=replica.deployment_id == "operational-0")
        endpoints[replica.deployment_id] = endpoint
        return endpoint

    pool = AdaptiveModelEndpointPool(
        replica_set,
        factory,
        failure_cooldown_seconds=60,
        max_failure_cooldown_seconds=60,
    )
    with pytest.raises(RuntimeError, match="replica failed"):
        pool.complete(_envelope(90), {"model": "qwen"})
    assert endpoints["operational-0"].calls == 1
    assert endpoints["operational-1"].calls == 0
    result = pool.complete(_envelope(91), {"model": "qwen"})
    assert result.response.deployment_id == "operational-1"


def test_explicit_pinned_replica_policy_never_falls_back() -> None:
    replica_set = ModelEndpointReplicaSet(
        tuple(_operational(index, capacity=1) for index in range(2))
    )
    endpoints = {}

    def factory(replica):
        endpoint = _FailingEndpoint(replica, fail=replica.deployment_id == "operational-1")
        endpoints[replica.deployment_id] = endpoint
        return endpoint

    pool = AdaptiveModelEndpointPool(
        replica_set,
        factory,
        selection_policy=PinnedReplicaSelectionPolicy("operational-1"),
        failure_cooldown_seconds=60,
        max_failure_cooldown_seconds=60,
    )
    with pytest.raises(RuntimeError, match="replica failed"):
        pool.complete(_envelope(92), {"model": "qwen"})
    assert endpoints["operational-1"].calls == 1
    assert endpoints["operational-0"].calls == 0
    with pytest.raises(RuntimeError, match="unavailable replica"):
        pool.complete(_envelope(93), {"model": "qwen"})
    assert endpoints["operational-0"].calls == 0
    snapshot = pool.snapshot()
    assert snapshot.selection_policy_digest == PinnedReplicaSelectionPolicy(
        "operational-1"
    ).identity_digest

def test_prefix_affinity_uses_content_addressed_tool_bundle_identity() -> None:
    bundle = ArtifactBlobRef("9" * 64, 4096, "application/json")
    request = replace(_envelope(200), tool_schema_bundle=bundle, envelope_digest="")
    common = {
        "model": "qwen",
        "messages": ({"role": "user", "content": "same"},),
    }
    first = {
        **common,
        "tools": ({"type": "function", "function": {"name": "first"}},),
    }
    second = {
        **common,
        "tools": ({"type": "function", "function": {"name": "second"}},),
    }
    assert _request_prefix_affinity_keys(request, first, max_keys=32) == (
        _request_prefix_affinity_keys(request, second, max_keys=32)
    )
    without_bundle = _envelope(200)
    assert _request_prefix_affinity_keys(
        without_bundle, first, max_keys=32
    ) != _request_prefix_affinity_keys(
        without_bundle, second, max_keys=32
    )


def test_waiter_dispatch_avoids_broadcast_thundering_herd() -> None:
    binding = _binding(0, capacity=1)

    class SlowEndpoint:
        def __init__(self) -> None:
            self._route = ModelEndpointRoute(
                binding.deployment_id,
                binding.deployment_generation,
                binding.base_url,
            )

        @property
        def route(self):
            return self._route

        def complete(self, request):
            time.sleep(0.001)
            return ModelEndpointResponse(
                request_id=request.request.request_id,
                deployment_id=request.deployment_id,
                text="ok",
            )

    pool = AdaptiveModelEndpointPool(
        ModelEndpointReplicaSet((binding,)),
        lambda _binding: SlowEndpoint(),
    )
    selection_calls = 0
    original = pool._selected_waiter_locked

    def counted():
        nonlocal selection_calls
        selection_calls += 1
        return original()

    pool._selected_waiter_locked = counted
    request_count = 64
    body = {
        "model": "qwen",
        "messages": ({"role": "user", "content": "x"},),
    }
    with ThreadPoolExecutor(max_workers=request_count) as executor:
        futures = [
            executor.submit(pool.complete, _envelope(index + 400), body)
            for index in range(request_count)
        ]
        for future in futures:
            future.result(timeout=5.0)

    # Targeted waiter signaling keeps scheduling work linear in queued
    # requests. The old global notify_all path grows quadratically and exceeds
    # this bound by a wide margin even at this modest queue depth.
    assert selection_calls <= request_count * 10


def test_pool_reuses_successful_generation_prefix_affinity_when_pressure_is_equal() -> None:
    bindings = tuple(_binding(index, capacity=2) for index in range(2))
    replica_set = ModelEndpointReplicaSet(bindings)
    endpoints = {}

    def factory(binding):
        endpoint = _FailingEndpoint(binding, fail=False)
        endpoints[binding.deployment_id] = endpoint
        return endpoint

    pool = AdaptiveModelEndpointPool(replica_set, factory)
    body = {
        "model": "qwen",
        "messages": (
            {"role": "system", "content": "stable system prefix"},
            {"role": "user", "content": "same request"},
        ),
    }

    first = pool.complete(_envelope(201), body)
    second = pool.complete(_envelope(202), body)

    assert first.response.deployment_id == "replica-0"
    assert second.response.deployment_id == "replica-0"
    snapshot = {row.deployment_id: row for row in pool.snapshot().replicas}
    assert snapshot["replica-0"].prefix_affinity_entries > 0
    assert snapshot["replica-0"].prefix_affinity_selections == 1
    assert snapshot["replica-1"].prefix_affinity_entries == 0


def test_prefix_affinity_never_overrides_live_parallel_pressure() -> None:
    bindings = tuple(_binding(index, capacity=1) for index in range(2))
    replica_set = ModelEndpointReplicaSet(bindings)
    warm_endpoints = {}

    def warm_factory(binding):
        endpoint = _FailingEndpoint(binding, fail=False)
        warm_endpoints[binding.deployment_id] = endpoint
        return endpoint

    pool = AdaptiveModelEndpointPool(replica_set, warm_factory)
    body = {
        "model": "qwen",
        "messages": (
            {"role": "system", "content": "stable system prefix"},
            {"role": "user", "content": "same request"},
        ),
    }
    pool.complete(_envelope(210), body)

    runtime = pool._runtimes["replica-0"]
    runtime.in_flight = 1
    try:
        result = pool.complete(_envelope(211), body)
    finally:
        runtime.in_flight = 0

    assert result.response.deployment_id == "replica-1"

def test_project_provider_single_flights_concurrent_first_binding() -> None:
    replica_set = ModelEndpointReplicaSet((_binding(0), _binding(1)))
    materialized: list[ModelEndpointReplicaSet] = []
    materialized_lock = Lock()
    build_entered = Event()
    release_build = Event()

    def replica_pool_factory(value: ModelEndpointReplicaSet):
        with materialized_lock:
            materialized.append(value)
            build_entered.set()
        if not release_build.wait(5):
            raise TimeoutError("single-flight test build gate did not open")
        return object()

    provider = QualifiedModelProjectProvider(
        ModelProviderProfile("replicated", ("generation","chat")),
        _ReplicaBindings(replica_set),
        replica_pool_factory,
        _RecorderStub(),
        FixedModelRequestTokenizationProvider(),
    )
    requirement = ModelCapabilityRequirement(
        role="reasoner",
        prompt_generation_id="prompt-v1",
        prompt_id="prompt",
        prompt_digest="1" * 64,
        required_capabilities=("chat",),
    )

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [
            executor.submit(provider.bind_capability, requirement)
            for _ in range(16)
        ]
        assert build_entered.wait(3)
        time.sleep(0.1)
        with materialized_lock:
            assert len(materialized) == 1
        release_build.set()
        clients = [future.result(timeout=3) for future in futures]

    assert all(client is clients[0] for client in clients)
    assert materialized == [replica_set]

def test_capacity_rejection_reduces_adaptive_window_immediately() -> None:
    binding = _binding(0, capacity=8)
    pool = AdaptiveModelEndpointPool(
        ModelEndpointReplicaSet((binding,)),
        lambda row: _CapacityEndpoint(row),
    )
    before = pool.snapshot().replicas[0]
    assert before.adaptive_limit == 4

    with pytest.raises(ModelEndpointError, match="overloaded"):
        pool.complete(
            _envelope(390),
            {
                "model": "qwen",
                "messages": ({"role": "user", "content": "pressure"},),
            },
        )

    after = pool.snapshot().replicas[0]
    assert after.adaptive_limit == 3
    assert after.request_rejections == 1
    assert after.failures == 0


def test_pool_backpressures_when_all_healthy_replicas_are_temporarily_saturated() -> None:
    replica_set = ModelEndpointReplicaSet((_binding(0, capacity=1),))
    gate = Event()
    lock = Lock()
    entered: list[str] = []
    pool = AdaptiveModelEndpointPool(
        replica_set,
        lambda binding: _GateEndpoint(binding, gate, entered, lock),
    )
    body = {
        "model": "qwen",
        "messages": ({"role": "user", "content": "queued"},),
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(pool.complete, _envelope(301), body)
        deadline = time.monotonic() + 3
        while len(entered) < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert entered == ["replica-0"]

        second = executor.submit(pool.complete, _envelope(302), body)
        time.sleep(0.1)
        assert entered == ["replica-0"]
        assert second.done() is False

        gate.set()
        assert first.result(timeout=3).response.deployment_id == "replica-0"
        assert second.result(timeout=3).response.deployment_id == "replica-0"

    snapshot = pool.snapshot().replicas[0]
    assert snapshot.completed == 2
    assert snapshot.in_flight == 0


def test_pinned_replica_backpressures_instead_of_falling_back_when_saturated() -> None:
    replica_set = ModelEndpointReplicaSet(
        (_operational(0, capacity=1), _operational(1, capacity=1))
    )
    gate = Event()
    lock = Lock()
    entered: list[str] = []
    pool = AdaptiveModelEndpointPool(
        replica_set,
        lambda replica: _GateEndpoint(replica, gate, entered, lock),
        selection_policy=PinnedReplicaSelectionPolicy("operational-1"),
    )
    body = {"model": "qwen"}

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(pool.complete, _envelope(311), body)
        deadline = time.monotonic() + 3
        while len(entered) < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert entered == ["operational-1"]

        second = executor.submit(pool.complete, _envelope(312), body)
        time.sleep(0.1)
        assert entered == ["operational-1"]
        assert second.done() is False

        gate.set()
        first.result(timeout=3)
        second.result(timeout=3)

    assert entered == ["operational-1", "operational-1"]
    assert all(
        row.completed == (2 if row.deployment_id == "operational-1" else 0)
        for row in pool.snapshot().replicas
    )


def test_pool_backpressure_is_owner_fair_under_asymmetric_fanout() -> None:
    replica_set = ModelEndpointReplicaSet((_binding(0, capacity=1),))
    gate = Event()
    lock = Lock()
    entered: list[str] = []
    pool = AdaptiveModelEndpointPool(
        replica_set,
        lambda binding: _OwnerGateEndpoint(binding, gate, entered, lock),
    )
    body = {
        "model": "qwen",
        "messages": ({"role": "user", "content": "queued"},),
    }

    with ThreadPoolExecutor(max_workers=4) as executor:
        first = executor.submit(pool.complete, _owned_envelope("paper-A", 0), body)
        deadline = time.monotonic() + 3
        while len(entered) < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert entered == ["paper-A"]

        queued = (
            executor.submit(pool.complete, _owned_envelope("paper-A", 1), body),
            executor.submit(pool.complete, _owned_envelope("paper-A", 2), body),
            executor.submit(pool.complete, _owned_envelope("paper-B", 0), body),
        )
        time.sleep(0.1)
        assert entered == ["paper-A"]

        gate.set()
        first.result(timeout=3)
        for future in queued:
            future.result(timeout=3)

    assert entered[1] == "paper-B"
    assert entered.count("paper-A") == 3
    assert entered.count("paper-B") == 1
