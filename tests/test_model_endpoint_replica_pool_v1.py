from __future__ import annotations

from tests.model_endpoint_test_support import make_test_model_endpoint_pool

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event, Lock
import time

import pytest

from noetrium_platform.capabilities.model.api import (
    model_capability_requirement_unit,
    ModelProviderProfile,
)
from noetrium_platform.capabilities.model.providers.project import QualifiedModelProjectProvider
from noetrium_platform.capabilities.model.request.api import ModelRequestEnvelope, model_lifetime_flow_id
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointError,
    ModelEndpointResponse,
    ModelEndpointRoute,
    ModelStreamEvent,
    ModelStreamEventKind,
    OperationalModelEndpointReplica,
    ModelEndpointReplicaSet,
    QualifiedModelEndpointBinding,
    ModelEndpointReplicaSet,
    ModelRuntimePressureSnapshot,
)
from noetrium_platform.capabilities.model.serving.endpoint.runtime import (
    AdaptiveModelEndpointPool,
    ModelEndpointPoolUnavailable,
    PinnedReplicaSelectionPolicy,
)
from noetrium_platform.capabilities.model.serving.endpoint.runtime.replica_pool import (
    MODEL_TOKEN_PREFIX_LOOKUP_COMPLEXITY,
    _FlowAdmissionClass,
    _PoolWaiter,
    _TokenPrefixResidencyIndex,
)
from noetrium_platform.evidence.artifact.content.api import ArtifactBlobRef
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    ImmutableModelIdentity,
    canonical_bytes,
    canonical_digest,
)
from tests._model_tokenization_support import FixedModelRequestTokenizationProvider


def _tenant_virtual_service_quanta(
    pool: AdaptiveModelEndpointPool,
    tenant_id: str,
) -> int:
    state = pool._scheduling_authority._tenant_states.get(tenant_id)
    return pool._scheduling_authority._state_snapshot(state)[1]


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


def _binding(
    index: int,
    *,
    capacity: int = 2,
    latency_isolation_concurrency: int | None = None,
    max_prefill_tokens: int = 4096,
    prefill_tokens_per_second: float = 1_000_000_000.0,
    output_tokens_per_second: float = 1_000_000_000.0,
) -> QualifiedModelEndpointBinding:
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
        latency_isolation_concurrency=(
            capacity
            if latency_isolation_concurrency is None
            else latency_isolation_concurrency
        ),
        preemptive_latency_isolation=False,
        preemptive_return_ttft_p99_seconds=None,
        preemptive_return_tpot_p99_seconds=None,
        max_prefill_queued_tokens=max_prefill_tokens,
        prefill_input_tokens_per_second=prefill_tokens_per_second,
        minimum_output_tokens_per_second=output_tokens_per_second,
        runtime_canary_evidence_digests=(f"{300 + index:064x}",),
        tokenizer_sha256="e" * 64,
        chat_template_sha256="f" * 64,
        verified_capabilities=("generation","chat"),
    )


def test_qualified_transport_liveness_budget_comes_from_frozen_evidence() -> None:
    binding = replace(
        _binding(
            0,
            capacity=4,
            max_prefill_tokens=400,
            prefill_tokens_per_second=100.0,
            output_tokens_per_second=20.0,
        ),
        preferred_admitted_concurrency=4,
        preemptive_latency_isolation=True,
        preemptive_return_ttft_p99_seconds=1.0,
        preemptive_return_tpot_p99_seconds=0.1,
    )
    total, idle = AdaptiveModelEndpointPool._qualified_transport_budget_seconds(
        binding, input_tokens=50, requested_output_tokens=10,
    )
    assert total == pytest.approx(6.0)
    assert idle == pytest.approx(4.2)

    # Missing output reservation must remain finite without inventing a small
    # wall-clock default: the frozen model context is the conservative bound.
    total_without_reservation, idle_without_reservation = (
        AdaptiveModelEndpointPool._qualified_transport_budget_seconds(
            binding, input_tokens=50, requested_output_tokens=0,
        )
    )
    assert total_without_reservation == pytest.approx(
        4.0 + (binding.model.context_length - 50) * 0.2
    )
    assert idle_without_reservation == pytest.approx(4.2)


def test_qualified_stream_wires_finite_total_and_idle_deadlines_after_admission() -> None:
    binding = replace(
        _binding(
            0,
            capacity=4,
            max_prefill_tokens=400,
            prefill_tokens_per_second=100.0,
            output_tokens_per_second=20.0,
        ),
        preferred_admitted_concurrency=4,
        preemptive_latency_isolation=True,
        preemptive_return_ttft_p99_seconds=1.0,
        preemptive_return_tpot_p99_seconds=0.1,
    )
    observed = {}

    class Endpoint:
        def __init__(self, qualified_binding):
            self._route = ModelEndpointRoute(
                qualified_binding.deployment_id,
                qualified_binding.deployment_generation,
                qualified_binding.base_url,
            )

        @property
        def route(self):
            return self._route

        def stream(self, request, on_event, *, stream_idle_timeout_s):
            observed["total"] = request.timeout_s
            observed["idle"] = stream_idle_timeout_s
            on_event(ModelStreamEvent(
                kind=ModelStreamEventKind.TEXT_DELTA,
                sequence=1,
                provider_event_type="chunk",
                provider_id="test",
                text_delta="ok",
            ))
            return ModelEndpointResponse(
                request_id=request.request.request_id,
                deployment_id=request.deployment_id,
                text="ok",
                output_tokens=1,
            )

    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)), Endpoint,
    )
    body = {
        "model": "qwen",
        "messages": ({"role": "user", "content": "bounded physical IO"},),
    }
    result = pool.stream(
        _envelope(991),
        body,
        lambda _event: None,
        input_tokens=50,
        input_token_ids=tuple(range(50)),
        requested_output_tokens=10,
    )
    assert result.response.text == "ok"
    assert observed["total"] == pytest.approx(6.0)
    assert observed["idle"] == pytest.approx(4.2)


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


class _PrefillStreamingEndpoint:
    def __init__(
        self,
        binding,
        *,
        first_event_gate: Event,
        first_decode_gate: Event,
        first_entered: Event,
        second_entered: Event,
    ) -> None:
        self._route = ModelEndpointRoute(
            binding.deployment_id,
            binding.deployment_generation,
            binding.base_url,
        )
        self._first_event_gate = first_event_gate
        self._first_decode_gate = first_decode_gate
        self._first_entered = first_entered
        self._second_entered = second_entered

    @property
    def route(self):
        return self._route

    def stream(self, request, on_event, *, stream_idle_timeout_s=30.0):
        request_id = request.request.request_id
        if request_id == "request-0":
            self._first_entered.set()
            if not self._first_event_gate.wait(5):
                raise TimeoutError("first prefill event gate did not open")
        else:
            self._second_entered.set()
        on_event(
            ModelStreamEvent(
                kind=ModelStreamEventKind.TEXT_DELTA,
                sequence=1,
                provider_event_type="chunk",
                provider_id="test",
                text_delta="x",
            )
        )
        if request_id == "request-0" and not self._first_decode_gate.wait(5):
            raise TimeoutError("first decode gate did not open")
        return ModelEndpointResponse(
            request_id=request_id,
            deployment_id=request.deployment_id,
            text="ok",
            output_tokens=1,
        )


def test_prefill_release_preserves_kv_token_reservation_until_completion() -> None:
    first_event_gate = Event()
    first_decode_gate = Event()
    first_entered = Event()
    second_entered = Event()
    binding = _binding(
        0,
        capacity=2,
        max_prefill_tokens=10,
    )
    endpoint = _PrefillStreamingEndpoint(
        binding,
        first_event_gate=first_event_gate,
        first_decode_gate=first_decode_gate,
        first_entered=first_entered,
        second_entered=second_entered,
    )
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)),
        lambda _binding: endpoint,
    )
    body = {"model": "qwen", "messages": [{"role": "user", "content": "x"}]}

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            pool.stream,
            _envelope(0),
            body,
            lambda _event: None,
            input_tokens=8,
            requested_output_tokens=1,
        )
        assert first_entered.wait(1)
        snapshot = pool.snapshot().replicas[0]
        assert snapshot.prefill_tokens_in_flight == 8
        assert snapshot.token_reservation_in_flight == 9
        assert snapshot.max_prefill_queued_tokens == 10

        second = executor.submit(
            pool.stream,
            _envelope(1),
            body,
            lambda _event: None,
            input_tokens=8,
            requested_output_tokens=1,
        )
        assert not second_entered.wait(0.1)

        # First provider output ends prefill, but prompt KV plus the reserved
        # decode budget remain resident until the request completes. A second
        # long request must therefore stay queued even though prefill capacity
        # itself has been released.
        first_event_gate.set()
        assert not second_entered.wait(0.1)
        during_decode = pool.snapshot().replicas[0]
        assert during_decode.prefill_tokens_in_flight == 0
        assert during_decode.token_reservation_in_flight == 9
        assert not first.done()

        first_decode_gate.set()
        assert first.result(timeout=2).response.text == "ok"
        assert second_entered.wait(1)
        assert second.result(timeout=2).response.text == "ok"

    final = pool.snapshot().replicas[0]
    assert final.prefill_tokens_in_flight == 0
    assert final.token_reservation_in_flight == 0


def test_single_replica_skips_prefix_affinity_bookkeeping() -> None:
    binding = _binding(0, capacity=2)
    pool = make_test_model_endpoint_pool(
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
    assert snapshot.replicas[0].token_prefix_sequences == 0
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
        latency_isolation_concurrency=1,
        preemptive_latency_isolation=second.preemptive_latency_isolation,
        preemptive_return_ttft_p99_seconds=(
            second.preemptive_return_ttft_p99_seconds
        ),
        preemptive_return_tpot_p99_seconds=(
            second.preemptive_return_tpot_p99_seconds
        ),
        max_prefill_queued_tokens=4096,
        prefill_input_tokens_per_second=1000.0,
        minimum_output_tokens_per_second=100.0,
        runtime_canary_evidence_digests=second.runtime_canary_evidence_digests,
        tokenizer_sha256=second.tokenizer_sha256,
        chat_template_sha256=second.chat_template_sha256,
    )
    with pytest.raises(ValueError, match="same immutable model"):
        ModelEndpointReplicaSet((first, drifted))


def test_provider_waiting_is_demand_not_capacity_pressure() -> None:
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((_binding(0, capacity=8),)),
        _CapacityEndpoint,
    )
    runtime = pool._runtimes["replica-0"]
    initial_limit = runtime.adaptive_window.limit

    first = ModelRuntimePressureSnapshot(
        deployment_id="replica-0",
        observed_monotonic=0.0,
        requests_running=1,
        requests_waiting=7,
        gpu_kv_cache_usage=0.5,
        preemptions_total=0,
    )
    with pool._cv:
        pool._apply_runtime_pressure_locked(runtime, first)
    assert runtime.adaptive_window.limit == initial_limit

    preempted = ModelRuntimePressureSnapshot(
        deployment_id="replica-0",
        observed_monotonic=1.0,
        requests_running=3,
        requests_waiting=5,
        gpu_kv_cache_usage=0.5,
        preemptions_total=1,
    )
    with pool._cv:
        pool._apply_runtime_pressure_locked(runtime, preempted)
    assert runtime.adaptive_window.limit == max(
        1,
        min(initial_limit - 1, 3),
    )


def test_stale_runtime_pressure_cannot_permanently_starve_replica() -> None:
    clock = [0.0]
    bindings = (_binding(0, capacity=2), _binding(1, capacity=2))
    pool = make_test_model_endpoint_pool(
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
            pool._selection_candidate_locked((), frozenset(), 0, owner_id="test-owner", admission_class=_FlowAdmissionClass.NORMAL)
        )
    assert fresh_binding.deployment_id == "replica-1"

    clock[0] = 4.0
    with pool._cv:
        _now, stale_binding, _runtime, _depth, _cooling = (
            pool._selection_candidate_locked((), frozenset(), 0, owner_id="test-owner", admission_class=_FlowAdmissionClass.NORMAL)
        )
    assert stale_binding.deployment_id == "replica-0"


def test_owner_head_heap_reconstructs_stale_candidates_from_live_queue() -> None:
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((_binding(0, capacity=1),)),
        _CapacityEndpoint,
    )
    with pool._cv:
        first = _PoolWaiter(81, "first-owner", 0.0)
        second = _PoolWaiter(82, "other-owner", 1.0)
        pool._enqueue_waiter_locked(first)
        pool._enqueue_waiter_locked(second)
        pool._waiter_owner_heap.clear()
        pool._invalidate_waiter_selection_locked()
        selected = pool._selected_waiter_locked()
        assert selected is not None
        assert selected.ticket in (81, 82)
        assert pool._waiter_owner_heap
        pool._remove_waiter_locked(first)
        pool._remove_waiter_locked(second)
        assert pool._waiter_count == 0
    pool.close()


def test_owner_head_lazy_heap_is_amortized_bounded() -> None:
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((_binding(0, capacity=1),)),
        _CapacityEndpoint,
    )
    with pool._cv:
        waiter = pool._waiters_by_ticket.get(0)
        if waiter is not None:
            raise AssertionError("unexpected preexisting waiter")
        from noetrium_platform.capabilities.model.serving.endpoint.runtime.replica_pool import _PoolWaiter
        waiter = _PoolWaiter(0, "paper-a", float(0))
        pool._enqueue_waiter_locked(waiter)
        for sequence in range(2000):
            pool._scheduling_authority.record_grant(
                tenant_id="paper-a",
                flow_id="paper-a",
                reserved_service_quanta=1,
            )
            pool._scheduling_authority.record_completion(
                tenant_id="paper-a",
                flow_id="paper-a",
                service_quanta=1,
                reserved_service_quanta=1,
            )
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

    pool = make_test_model_endpoint_pool(replica_set, factory)

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

    pool = make_test_model_endpoint_pool(
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
    requirement = model_capability_requirement_unit(
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
    pool = make_test_model_endpoint_pool(
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

    pool = make_test_model_endpoint_pool(
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

    pool = make_test_model_endpoint_pool(
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

def test_token_prefix_residency_matches_exact_token_identity() -> None:
    index = _TokenPrefixResidencyIndex(
        ("replica-0", "replica-1"),
        {"replica-0": 32, "replica-1": 32},
    )
    index.record("replica-0", (1, 2, 3, 4, 5))
    index.record("replica-1", (1, 2, 9))

    mask, depth = index.longest_prefix((1, 2, 3, 4, 8))
    assert depth == 4
    assert mask == 1

    mask, depth = index.longest_prefix((1, 2, 9, 10))
    assert depth == 3
    assert mask == 2

    mask, depth = index.longest_prefix((7, 8))
    assert depth == 0
    assert mask == 3


def test_token_prefix_lookup_complexity_contract_is_tight_linear() -> None:
    contract = MODEL_TOKEN_PREFIX_LOOKUP_COMPLEXITY
    assert contract.time_upper_bound == contract.time_lower_bound
    assert contract.space_upper_bound == contract.space_lower_bound
    assert contract.time_upper_bound.variables == ("input_tokens",)

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

    pool = make_test_model_endpoint_pool(
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

    pool = make_test_model_endpoint_pool(replica_set, factory)
    body = {
        "model": "qwen",
        "messages": (
            {"role": "system", "content": "stable system prefix"},
            {"role": "user", "content": "same request"},
        ),
    }

    token_ids = tuple(range(1, 17))
    first = pool.complete(
        _envelope(201),
        body,
        input_tokens=len(token_ids),
        input_token_ids=token_ids,
    )
    second = pool.complete(
        _envelope(202),
        body,
        input_tokens=len(token_ids),
        input_token_ids=token_ids,
    )

    assert first.response.deployment_id == "replica-0"
    assert second.response.deployment_id == "replica-0"
    snapshot = {row.deployment_id: row for row in pool.snapshot().replicas}
    assert snapshot["replica-0"].token_prefix_sequences == 1
    assert snapshot["replica-0"].token_prefix_tokens == len(token_ids)
    assert snapshot["replica-0"].prefix_affinity_selections == 1
    assert snapshot["replica-1"].token_prefix_sequences == 0


def test_dispatch_wait_does_not_consume_provider_timeout() -> None:
    binding = _binding(0, capacity=1)
    gate = Event()
    entered: list[str] = []
    lock = Lock()
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)),
        lambda row: _GateEndpoint(row, gate, entered, lock),
    )
    body = {
        "model": "qwen",
        "messages": ({"role": "user", "content": "capacity wait"},),
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(pool.complete, _envelope(901), body)
        deadline = time.monotonic() + 2.0
        while len(entered) < 1 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert entered == ["replica-0"]

        # timeout_s is provider-only. Queueing behind a qualified capacity
        # claim must not turn it into a local dispatch deadline.
        second = executor.submit(
            pool.complete,
            _envelope(902),
            body,
            timeout_s=0.05,
        )
        time.sleep(0.1)
        assert not second.done()
        assert pool._waiter_count == 1
        assert pool.snapshot().replicas[0].in_flight == 1

        gate.set()
        assert first.result(timeout=2).response.deployment_id == "replica-0"
        assert second.result(timeout=2).response.deployment_id == "replica-0"

    assert pool._waiter_count == 0
    assert pool.snapshot().replicas[0].in_flight == 0


def test_prefix_affinity_never_overrides_live_parallel_pressure() -> None:
    bindings = tuple(_binding(index, capacity=1) for index in range(2))
    replica_set = ModelEndpointReplicaSet(bindings)
    warm_endpoints = {}

    def warm_factory(binding):
        endpoint = _FailingEndpoint(binding, fail=False)
        warm_endpoints[binding.deployment_id] = endpoint
        return endpoint

    pool = make_test_model_endpoint_pool(replica_set, warm_factory)
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
    requirement = model_capability_requirement_unit(
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
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)),
        lambda row: _CapacityEndpoint(row),
    )
    before = pool.snapshot().replicas[0]
    assert before.adaptive_limit == 3

    with pytest.raises(ModelEndpointError, match="overloaded") as caught:
        pool.complete(
            _envelope(390),
            {
                "model": "qwen",
                "messages": ({"role": "user", "content": "pressure"},),
            },
        )

    after = pool.snapshot().replicas[0]
    assert after.adaptive_limit < before.adaptive_limit
    # Every retry is an explicitly certified capacity rejection, rather than a
    # physical replica failure or an unobserved side effect.
    assert after.request_rejections == len(caught.value.dispatch_attempts)
    assert after.request_rejections >= 1
    assert after.failures == 0


def test_pool_backpressures_when_all_healthy_replicas_are_temporarily_saturated() -> None:
    replica_set = ModelEndpointReplicaSet((_binding(0, capacity=1),))
    gate = Event()
    lock = Lock()
    entered: list[str] = []
    pool = make_test_model_endpoint_pool(
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
    pool = make_test_model_endpoint_pool(
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
    pool = make_test_model_endpoint_pool(
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


def test_token_prefix_lookup_finds_global_longest_prefix_once() -> None:
    bindings = tuple(_binding(index, capacity=2) for index in range(8))
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet(bindings),
        _CapacityEndpoint,
    )
    query = tuple(range(16))
    with pool._cv:
        for index, deployment_id in enumerate(pool._runtimes):
            pool._token_prefix_residency.record(
                deployment_id,
                query[: index + 1],
            )

        mask, depth = pool._token_prefix_residency.longest_prefix(query)
        assert depth == 8
        assert mask == pool._replica_bit_by_deployment["replica-7"]
        _now, binding, _runtime, selected_depth, _cooling = (
            pool._selection_candidate_locked(
                query,
                frozenset(),
                len(query),
                owner_id="test-owner",
                admission_class=_FlowAdmissionClass.NORMAL,
            )
        )
    assert binding is not None
    assert binding.deployment_id == "replica-7"
    assert selected_depth == 8


def test_token_prefix_eviction_updates_shared_replica_mask_exactly() -> None:
    index = _TokenPrefixResidencyIndex(
        ("replica-0", "replica-1"),
        {"replica-0": 2, "replica-1": 2},
    )
    shared = (1, 2)
    index.record("replica-0", shared)
    index.record("replica-1", shared)
    mask, depth = index.longest_prefix((1, 2, 3))
    assert depth == 2
    assert mask == 3

    index.record("replica-0", (3, 4))
    mask, depth = index.longest_prefix((1, 2, 3))
    assert depth == 2
    assert mask == 2

    index.record("replica-1", (5, 6))
    mask, depth = index.longest_prefix((1, 2, 3))
    assert depth == 0
    assert mask == 3


def test_owner_fairness_uses_token_service_not_request_count() -> None:
    from noetrium_platform.capabilities.model.serving.endpoint.runtime.replica_pool import (
        _PoolWaiter,
    )

    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((_binding(0, capacity=4),)),
        _CapacityEndpoint,
    )
    with pool._cv:
        a_first = _PoolWaiter(0, "paper-a", float(0))
        a_second = _PoolWaiter(1, "paper-a", float(1))
        b_first = _PoolWaiter(2, "paper-b", float(2))
        pool._next_waiter_ticket = 3
        pool._enqueue_waiter_locked(a_first)
        pool._enqueue_waiter_locked(a_second)
        pool._enqueue_waiter_locked(b_first)

        assert pool._selected_waiter_locked() is a_first
        pool._remove_waiter_locked(a_first)
        runtime = pool._runtimes["replica-0"]
        binding = pool._bindings["replica-0"]
        pool._admit_selected_locked(
            owner_id="paper-a",
            binding=binding,
            runtime=runtime,
            prefix_affinity_depth=0,
            input_tokens=128,
        )

        # A already received 128 input-token service while B received zero;
        # B must be the next owner even though both have one active/queued
        # request shape under the old request-count policy.
        assert _tenant_virtual_service_quanta(pool, "paper-a") == 128
        assert pool._selected_waiter_locked() is b_first


def test_rejoining_owner_uses_global_cumulative_service_without_local_counter() -> None:
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((_binding(0, capacity=2),)),
        _CapacityEndpoint,
    )
    scheduling = pool._scheduling_authority
    scheduling.record_grant(
        tenant_id="backlogged",
        flow_id="backlogged",
        reserved_service_quanta=500,
    )
    scheduling.record_completion(
        tenant_id="backlogged",
        flow_id="backlogged",
        service_quanta=500,
        reserved_service_quanta=500,
    )
    scheduling.record_grant(
        tenant_id="rejoin",
        flow_id="rejoin",
        reserved_service_quanta=10,
    )
    scheduling.record_completion(
        tenant_id="rejoin",
        flow_id="rejoin",
        service_quanta=10,
        reserved_service_quanta=10,
    )
    with pool._cv:
        existing = _PoolWaiter(0, "backlogged", 0.0)
        rejoin = _PoolWaiter(1, "rejoin", 1.0)
        pool._next_waiter_ticket = 2
        pool._enqueue_waiter_locked(existing)
        pool._enqueue_waiter_locked(rejoin)
        assert _tenant_virtual_service_quanta(pool, "backlogged") == 500
        # Re-entering after all siblings went idle inherits the last active
        # service frontier before its own service is charged: 500 + 10.
        # It cannot create idle-time credit by switching logical ownership.
        assert _tenant_virtual_service_quanta(pool, "rejoin") == 510
        assert pool._selected_waiter_locked() is existing
    assert not hasattr(pool, "_owner_service_quanta")


def test_completed_output_tokens_advance_owner_virtual_service() -> None:
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((_binding(0, capacity=2),)),
        _CapacityEndpoint,
    )
    runtime = pool._runtimes["replica-0"]
    binding = pool._bindings["replica-0"]
    with pool._cv:
        pool._admit_selected_locked(
            owner_id="paper",
            binding=binding,
            runtime=runtime,
            prefix_affinity_depth=0,
            input_tokens=11,
        )
    pool._finish(
        runtime,
        owner_id="paper",
        elapsed_seconds=0.1,
        admission_class=_FlowAdmissionClass.NORMAL,
        outcome="completed",
        charged_input_tokens=11,
        output_tokens=13,
    )
    assert _tenant_virtual_service_quanta(pool, "paper") == 100_000_000
    assert pool._owner_worker_deficit_locked("paper", 0) == -24



def test_output_budget_reservation_affects_fair_order_then_reconciles_actual() -> None:
    from noetrium_platform.capabilities.model.serving.endpoint.runtime.replica_pool import (
        _PoolWaiter,
    )

    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((_binding(0, capacity=4),)),
        _CapacityEndpoint,
    )
    with pool._cv:
        a_first = _PoolWaiter(0, "paper-a", float(0))
        a_second = _PoolWaiter(1, "paper-a", float(1))
        b_first = _PoolWaiter(2, "paper-b", float(2))
        pool._next_waiter_ticket = 3
        pool._enqueue_waiter_locked(a_first)
        pool._enqueue_waiter_locked(a_second)
        pool._enqueue_waiter_locked(b_first)
        pool._remove_waiter_locked(a_first)

        runtime = pool._runtimes["replica-0"]
        binding = pool._bindings["replica-0"]
        pool._admit_selected_locked(
            owner_id="paper-a",
            binding=binding,
            runtime=runtime,
            prefix_affinity_depth=0,
            input_tokens=10,
            requested_output_tokens=1000,
        )
        assert _tenant_virtual_service_quanta(pool, "paper-a") == 1010
        assert pool._selected_waiter_locked() is b_first

    pool._finish(
        runtime,
        owner_id="paper-a",
        elapsed_seconds=0.1,
        admission_class=_FlowAdmissionClass.NORMAL,
        outcome="completed",
        charged_input_tokens=10,
        output_tokens=20,
        reserved_output_tokens=1000,
    )
    assert _tenant_virtual_service_quanta(pool, "paper-a") == 100_000_000
    assert pool._owner_worker_deficit_locked("paper-a", 0) == -30


def test_failed_attempt_releases_output_budget_reservation() -> None:
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((_binding(0, capacity=2),)),
        _CapacityEndpoint,
    )
    runtime = pool._runtimes["replica-0"]
    binding = pool._bindings["replica-0"]
    with pool._cv:
        pool._admit_selected_locked(
            owner_id="paper",
            binding=binding,
            runtime=runtime,
            prefix_affinity_depth=0,
            input_tokens=7,
            requested_output_tokens=101,
        )
    pool._finish(
        runtime,
        owner_id="paper",
        elapsed_seconds=0.01,
        admission_class=_FlowAdmissionClass.NORMAL,
        outcome="request_rejected",
        charged_input_tokens=7,
        reserved_output_tokens=101,
    )
    assert _tenant_virtual_service_quanta(pool, "paper") == 10_000_000
    assert pool._owner_worker_deficit_locked("paper", 0) == -7



def test_virtual_service_uses_qualification_weighted_prefill_decode_cost() -> None:
    binding = _binding(
        0,
        prefill_tokens_per_second=1000.0,
        output_tokens_per_second=100.0,
    )
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)),
        _CapacityEndpoint,
    )
    runtime = pool._runtimes["replica-0"]
    frozen = pool._bindings["replica-0"]
    with pool._cv:
        pool._admit_selected_locked(
            owner_id="paper",
            binding=frozen,
            runtime=runtime,
            prefix_affinity_depth=0,
            input_tokens=100,
            requested_output_tokens=20,
        )
        assert _tenant_virtual_service_quanta(pool, "paper") == 300_000_000

    pool._finish(
        runtime,
        owner_id="paper",
        elapsed_seconds=0.3,
        admission_class=_FlowAdmissionClass.NORMAL,
        outcome="completed",
        charged_input_tokens=100,
        output_tokens=20,
        reserved_output_tokens=20,
    )
    # 100 prefill tokens @ 1000 tok/s = 0.1s; 20 decode tokens @
    # 100 tok/s = 0.2s. Fixed-point quanta are nanoseconds.
    assert pool._prefill_service_quanta_per_token == 1_000_000
    assert pool._output_service_quanta_per_token == 10_000_000
    assert _tenant_virtual_service_quanta(pool, "paper") == 300_000_000
    assert pool._owner_worker_deficit_locked("paper", 0) == -300_000_000


def test_worker_deficit_quantum_is_qualification_prefill_horizon() -> None:
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet(
            (
                _binding(
                    0,
                    max_prefill_tokens=40,
                    prefill_tokens_per_second=1000.0,
                    output_tokens_per_second=100.0,
                ),
                _binding(
                    1,
                    max_prefill_tokens=60,
                    prefill_tokens_per_second=1000.0,
                    output_tokens_per_second=100.0,
                ),
            )
        ),
        _CapacityEndpoint,
    )
    assert pool._prefill_service_quanta_per_token == 1_000_000
    assert pool._worker_deficit_quantum_quanta == 40_000_000


def test_worker_deficit_preserves_locality_then_forces_load_balance() -> None:
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet(
            (
                _binding(0, capacity=4, max_prefill_tokens=10),
                _binding(1, capacity=4, max_prefill_tokens=10),
            )
        ),
        _CapacityEndpoint,
    )
    token_ids = (1, 2, 3, 4, 5, 6)
    pool._token_prefix_residency.record("replica-0", token_ids)

    with pool._cv:
        first = pool._selection_candidate_locked(
            token_ids,
            frozenset(),
            6,
            owner_id="paper",
            admission_class=_FlowAdmissionClass.NORMAL,
        )
        assert first[1].deployment_id == "replica-0"
        pool._charge_worker_deficit_locked(
            "paper",
            "replica-0",
            input_tokens=6,
            requested_output_tokens=0,
        )

        second = pool._selection_candidate_locked(
            token_ids,
            frozenset(),
            6,
            owner_id="paper",
            admission_class=_FlowAdmissionClass.NORMAL,
        )
        assert second[1].deployment_id == "replica-0"
        pool._charge_worker_deficit_locked(
            "paper",
            "replica-0",
            input_tokens=6,
            requested_output_tokens=0,
        )

        # replica-0 has now spent more than one Qw while replica-1 remains
        # positive. D2LPM must stop following locality and load-balance.
        third = pool._selection_candidate_locked(
            token_ids,
            frozenset(),
            6,
            owner_id="paper",
            admission_class=_FlowAdmissionClass.NORMAL,
        )
        assert third[1].deployment_id == "replica-1"
        assert pool._owner_worker_deficit_snapshot_locked("paper") == (-2, 10)


def test_worker_deficit_refill_batches_exact_quantum_rounds() -> None:
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet(
            (
                _binding(0, max_prefill_tokens=10),
                _binding(1, max_prefill_tokens=10),
            )
        ),
        _CapacityEndpoint,
    )
    assert pool._worker_deficit_quantum_quanta == 10
    with pool._cv:
        pool._owner_worker_credit_quanta["paper"] = 0
        pool._owner_worker_debit_quanta["paper"] = {0: 100, 1: 50}
        pool._refill_owner_worker_deficits_locked("paper")
        # One O(1) lazy +60 refill produces the same exact deficits.
        assert pool._owner_worker_credit_quanta["paper"] == 60
        assert pool._owner_worker_deficit_snapshot_locked("paper") == (-40, 10)



def test_cached_input_receipt_reconciles_to_exact_extend_service() -> None:
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((_binding(0, capacity=2),)),
        _CapacityEndpoint,
    )
    runtime = pool._runtimes["replica-0"]
    binding = pool._bindings["replica-0"]
    with pool._cv:
        pool._admit_selected_locked(
            owner_id="paper",
            binding=binding,
            runtime=runtime,
            prefix_affinity_depth=0,
            input_tokens=100,
            requested_output_tokens=20,
        )
        assert _tenant_virtual_service_quanta(pool, "paper") == 120
        before = pool._owner_worker_deficit_locked("paper", 0)
        assert before == -120

    pool._finish(
        runtime,
        owner_id="paper",
        elapsed_seconds=0.1,
        admission_class=_FlowAdmissionClass.NORMAL,
        outcome="completed",
        charged_input_tokens=100,
        cached_input_tokens=80,
        output_tokens=10,
        reserved_output_tokens=20,
    )
    # Global fairness uses measured service time; worker locality reconciles to
    # exact 20 extend-input + 10 output token service.
    assert _tenant_virtual_service_quanta(pool, "paper") == 100_000_000
    assert pool._owner_worker_deficit_locked("paper", 0) == -30


def test_cached_receipt_reconciles_observed_usage_even_above_admission_estimate() -> None:
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((_binding(0, capacity=2),)),
        _CapacityEndpoint,
    )
    runtime = pool._runtimes["replica-0"]
    binding = pool._bindings["replica-0"]
    with pool._cv:
        pool._admit_selected_locked(
            owner_id="paper",
            binding=binding,
            runtime=runtime,
            prefix_affinity_depth=0,
            input_tokens=10,
            requested_output_tokens=20,
        )

    pool._finish(
        runtime,
        owner_id="paper",
        elapsed_seconds=0.1,
        admission_class=_FlowAdmissionClass.NORMAL,
        outcome="completed",
        charged_input_tokens=10,
        observed_input_tokens=100,
        cached_input_tokens=80,
        output_tokens=10,
        reserved_output_tokens=20,
    )

    # Admission reserved 10+20 tokens. Observed service was 20 uncached prompt
    # +10 output tokens: same total quanta, despite cache hits exceeding the
    # admission estimate. No in-flight state may leak.
    assert pool._owner_worker_deficit_locked("paper", 0) == -30
    assert runtime.in_flight == 0
    assert runtime.token_reservation_in_flight == 0


def test_missing_cached_input_receipt_remains_conservative_full_input() -> None:
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((_binding(0, capacity=2),)),
        _CapacityEndpoint,
    )
    runtime = pool._runtimes["replica-0"]
    binding = pool._bindings["replica-0"]
    with pool._cv:
        pool._admit_selected_locked(
            owner_id="paper",
            binding=binding,
            runtime=runtime,
            prefix_affinity_depth=0,
            input_tokens=100,
            requested_output_tokens=20,
        )

    pool._finish(
        runtime,
        owner_id="paper",
        elapsed_seconds=0.1,
        admission_class=_FlowAdmissionClass.NORMAL,
        outcome="completed",
        charged_input_tokens=100,
        cached_input_tokens=None,
        output_tokens=10,
        reserved_output_tokens=20,
    )
    assert _tenant_virtual_service_quanta(pool, "paper") == 100_000_000
    assert pool._owner_worker_deficit_locked("paper", 0) == -110



def test_worker_deficit_refill_is_constant_time_lazy_offset() -> None:
    bindings = tuple(_binding(index) for index in range(256))
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet(bindings),
        _CapacityEndpoint,
    )
    with pool._cv:
        pool._owner_worker_credit_quanta["paper"] = 0
        pool._owner_worker_debit_quanta["paper"] = {
            index: 100 + index
            for index in range(256)
        }
        debit_identity = id(pool._owner_worker_debit_quanta["paper"])
        before = dict(pool._owner_worker_debit_quanta["paper"])
        pool._refill_owner_worker_deficits_locked(
            "paper",
            maximum_eligible_deficit=-100,
        )
        assert id(pool._owner_worker_debit_quanta["paper"]) == debit_identity
        assert pool._owner_worker_debit_quanta["paper"] == before
        assert pool._owner_worker_credit_quanta["paper"] > 0
