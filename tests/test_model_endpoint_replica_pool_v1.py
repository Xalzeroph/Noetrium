from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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
    ModelEndpointResponse,
    ModelEndpointRoute,
    OperationalModelEndpointReplica,
    ModelEndpointReplicaSet,
    QualifiedModelEndpointBinding,
    ModelEndpointReplicaSet,
)
from noetrium_platform.capabilities.model.serving.endpoint.runtime import (
    AdaptiveModelEndpointPool,
    PinnedReplicaSelectionPolicy,
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
