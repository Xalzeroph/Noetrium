from __future__ import annotations

from tests.model_endpoint_test_support import make_test_model_endpoint_pool

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
import time

from noetrium_platform.capabilities.model.request.api import (
    ModelRequestEnvelope,
    model_lifetime_flow_id,
)
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointReplicaSet,
    ModelEndpointResponse,
    ModelEndpointRoute,
    QualifiedModelEndpointBinding,
)
from noetrium_platform.capabilities.model.serving.endpoint.runtime import (
    AdaptiveModelEndpointPool,
)
from noetrium_platform.foundation.kernel.concurrency.api import Deadline
from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import (
    UnifiedSchedulingAuthority,
)
from noetrium_platform.evidence.artifact.content.api import ArtifactBlobRef
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    ImmutableModelIdentity,
    canonical_bytes,
    canonical_digest,
)


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
    *,
    latency_isolation_concurrency: int = 1,
    preferred_admitted_concurrency: int | None = None,
    max_admitted_concurrency: int = 4,
    preemptive_latency_isolation: bool = False,
) -> QualifiedModelEndpointBinding:
    return QualifiedModelEndpointBinding(
        role="reasoner",
        capability_id="generation",
        input_schema_id="model.generation.request.v1",
        output_schema_id="model.generation.response.v1",
        deployment_id="replica-0",
        deployment_generation="1" * 64,
        base_url="http://127.0.0.1:18000",
        model=_model(),
        model_stack_digest="c" * 64,
        qualification_certificate_digest="2" * 64,
        runtime_qualification_digest="3" * 64,
        host_identity_digest="d" * 64,
        prompt_generation="prompt-v1",
        max_admitted_concurrency=max_admitted_concurrency,
        latency_isolation_concurrency=latency_isolation_concurrency,
        preemptive_latency_isolation=preemptive_latency_isolation,
        preemptive_return_ttft_p99_seconds=(
            0.01 if preemptive_latency_isolation else None
        ),
        preemptive_return_tpot_p99_seconds=(
            0.01 if preemptive_latency_isolation else None
        ),
        max_prefill_queued_tokens=65536,
        prefill_input_tokens_per_second=1_000_000_000.0,
        minimum_output_tokens_per_second=1_000_000_000.0,
        runtime_canary_evidence_digests=("4" * 64,),
        tokenizer_sha256="e" * 64,
        chat_template_sha256="f" * 64,
        verified_capabilities=("chat", "generation"),
        preferred_admitted_concurrency=(
            latency_isolation_concurrency
            if preferred_admitted_concurrency is None
            else preferred_admitted_concurrency
        ),
    )


def _request(
    request_id: str,
    *,
    tenant_id: str,
    lifetime_id: str | None = None,
) -> ModelRequestEnvelope:
    raw = canonical_bytes(
        {
            "model": "qwen",
            "messages": [{"role": "user", "content": request_id}],
        }
    )
    return ModelRequestEnvelope(
        schema_version="model-request.v1",
        request_id=request_id,
        context=ExecutionContext(
            run_id=f"run-{request_id}",
            trace_id=f"trace-{request_id}",
            span_id=f"span-{request_id}",
            execution_tenant_id=tenant_id,
            lifetime_id=lifetime_id,
        ),
        role="reasoner",
        model=_model(),
        prompt_generation_id="prompt-v1",
        prompt_id="prompt",
        prompt_digest="5" * 64,
        request_body=ArtifactBlobRef(
            canonical_digest({"request_id": request_id}),
            len(raw),
            "application/json",
        ),
    )


def test_live_flow_return_precedes_new_flow_until_lifetime_release() -> None:
    entered: list[str] = []
    lock = Lock()

    class Endpoint:
        def __init__(self, binding: QualifiedModelEndpointBinding) -> None:
            self._route = ModelEndpointRoute(
                binding.deployment_id,
                binding.deployment_generation,
                binding.base_url,
            )

        @property
        def route(self) -> ModelEndpointRoute:
            return self._route

        def complete(self, request) -> ModelEndpointResponse:
            with lock:
                entered.append(request.request.request_id)
            return ModelEndpointResponse(
                request_id=request.request.request_id,
                deployment_id=request.deployment_id,
                text="ok",
            )

    binding = _binding(
        latency_isolation_concurrency=1,
        max_admitted_concurrency=1,
    )
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)),
        Endpoint,
    )
    pool.complete(
        _request("A1", tenant_id="paper-a", lifetime_id="life-a"),
        {},
        input_tokens=1,
        requested_output_tokens=1,
    )
    first_snapshot = pool.snapshot()
    assert first_snapshot.reserved_flow_count == 1
    assert first_snapshot.active_flow_count == 0

    with ThreadPoolExecutor(max_workers=2) as executor:
        new_flow = executor.submit(
            pool.complete,
            _request("B1", tenant_id="paper-b", lifetime_id="life-b"),
            {},
            input_tokens=1,
            requested_output_tokens=1,
            timeout_s=5,
        )
        time.sleep(0.05)
        assert not new_flow.done()

        returning_flow = executor.submit(
            pool.complete,
            _request("A2", tenant_id="paper-a", lifetime_id="life-a"),
            {},
            input_tokens=1,
            requested_output_tokens=1,
            timeout_s=5,
        )
        assert returning_flow.result(timeout=2).response.text == "ok"
        time.sleep(0.05)
        assert not new_flow.done()

        pool.release_flow(model_lifetime_flow_id("life-a"))
        assert new_flow.result(timeout=2).response.text == "ok"

    pool.release_flow(model_lifetime_flow_id("life-b"))
    assert entered == ["A1", "A2", "B1"]
    final_snapshot = pool.snapshot()
    assert final_snapshot.reserved_flow_count == 0
    assert final_snapshot.pending_flow_release_count == 0
    pool.close()


def test_preemptive_qualified_borrower_uses_idle_slot_and_return_preempts() -> None:
    entered: list[tuple[str, int | None]] = []
    lock = Lock()
    borrower_entered = Event()
    protected_entered = Event()
    release_borrower = Event()

    class Endpoint:
        def __init__(self, binding: QualifiedModelEndpointBinding) -> None:
            self._route = ModelEndpointRoute(
                binding.deployment_id,
                binding.deployment_generation,
                binding.base_url,
            )

        @property
        def route(self) -> ModelEndpointRoute:
            return self._route

        def complete(self, request) -> ModelEndpointResponse:
            priority = request.body.get("priority")
            with lock:
                entered.append((request.request.request_id, priority))
            if request.request.request_id == "B1":
                borrower_entered.set()
                if not release_borrower.wait(5):
                    raise TimeoutError("borrower was not released")
            elif request.request.request_id == "A2":
                protected_entered.set()
                release_borrower.set()
            return ModelEndpointResponse(
                request_id=request.request.request_id,
                deployment_id=request.deployment_id,
                text="ok",
            )

    binding = _binding(
        latency_isolation_concurrency=1,
        max_admitted_concurrency=1,
        preemptive_latency_isolation=True,
    )
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)),
        Endpoint,
    )

    # Establish one durable idle protected reservation.
    first = pool.complete(
        _request("A1", tenant_id="paper-a", lifetime_id="life-a"),
        {},
        input_tokens=1,
        requested_output_tokens=1,
    )
    assert first.response.text == "ok"

    with ThreadPoolExecutor(max_workers=2) as executor:
        borrower = executor.submit(
            pool.complete,
            _request("B1", tenant_id="paper-b"),
            {},
            input_tokens=1,
            requested_output_tokens=1,
            timeout_s=5,
        )
        assert borrower_entered.wait(2)

        returning = executor.submit(
            pool.complete,
            _request("A2", tenant_id="paper-a", lifetime_id="life-a"),
            {},
            input_tokens=1,
            requested_output_tokens=1,
            timeout_s=5,
        )
        assert protected_entered.wait(2)
        assert returning.result(timeout=2).response.text == "ok"
        assert borrower.result(timeout=2).response.text == "ok"

    pool.release_flow(model_lifetime_flow_id("life-a"))
    assert ("B1", 1) in entered
    assert ("A2", -1) in entered
    # First request is normal class even on a priority-capable engine.
    assert entered[0] == ("A1", 0)
    pool.close()


def test_unqualified_hard_reservation_never_injects_vllm_priority() -> None:
    bodies: list[dict] = []

    class Endpoint:
        def __init__(self, binding: QualifiedModelEndpointBinding) -> None:
            self._route = ModelEndpointRoute(
                binding.deployment_id,
                binding.deployment_generation,
                binding.base_url,
            )

        @property
        def route(self) -> ModelEndpointRoute:
            return self._route

        def complete(self, request) -> ModelEndpointResponse:
            bodies.append(dict(request.body))
            return ModelEndpointResponse(
                request_id=request.request.request_id,
                deployment_id=request.deployment_id,
                text="ok",
            )

    binding = _binding(
        latency_isolation_concurrency=1,
        max_admitted_concurrency=1,
        preemptive_latency_isolation=False,
    )
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)),
        Endpoint,
    )
    pool.complete(
        _request("A1", tenant_id="paper-a", lifetime_id="life-a"),
        {},
        input_tokens=1,
        requested_output_tokens=1,
    )
    pool.complete(
        _request("A2", tenant_id="paper-a", lifetime_id="life-a"),
        {},
        input_tokens=1,
        requested_output_tokens=1,
    )
    pool.release_flow(model_lifetime_flow_id("life-a"))
    assert bodies == [{}, {}]
    pool.close()


def test_tenant_vtc_fairness_survives_transient_token_reservations() -> None:
    entered: list[str] = []
    lock = Lock()
    gate = Event()
    first_entered = Event()

    class Endpoint:
        def __init__(self, binding: QualifiedModelEndpointBinding) -> None:
            self._route = ModelEndpointRoute(
                binding.deployment_id,
                binding.deployment_generation,
                binding.base_url,
            )

        @property
        def route(self) -> ModelEndpointRoute:
            return self._route

        def complete(self, request) -> ModelEndpointResponse:
            with lock:
                entered.append(request.request.context.execution_tenant_id)
                if len(entered) == 1:
                    first_entered.set()
            if not gate.wait(5):
                raise TimeoutError("test endpoint gate did not open")
            return ModelEndpointResponse(
                request_id=request.request.request_id,
                deployment_id=request.deployment_id,
                text="ok",
            )

    binding = _binding(
        latency_isolation_concurrency=1,
        max_admitted_concurrency=1,
    )
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)),
        Endpoint,
    )
    with ThreadPoolExecutor(max_workers=3) as executor:
        first = executor.submit(
            pool.complete,
            _request("A1", tenant_id="paper-a"),
            {},
            input_tokens=100,
            requested_output_tokens=1,
            timeout_s=5,
        )
        assert first_entered.wait(2)
        second_a = executor.submit(
            pool.complete,
            _request("A2", tenant_id="paper-a"),
            {},
            input_tokens=1,
            requested_output_tokens=1,
            timeout_s=5,
        )
        first_b = executor.submit(
            pool.complete,
            _request("B1", tenant_id="paper-b"),
            {},
            input_tokens=1,
            requested_output_tokens=1,
            timeout_s=5,
        )
        deadline = time.monotonic() + 2.0
        while True:
            with pool._cv:
                queued = pool._waiter_count
            if queued == 2:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("model fairness waiters did not both enqueue")
            time.sleep(0.005)
        gate.set()
        first.result(timeout=2)
        second_a.result(timeout=2)
        first_b.result(timeout=2)

    assert entered == ["paper-a", "paper-b", "paper-a"]
    pool.close()


def test_preferred_interactive_frontier_is_distinct_from_strict_isolation_and_hard_max() -> None:
    class Endpoint:
        def __init__(self, binding: QualifiedModelEndpointBinding) -> None:
            self._route = ModelEndpointRoute(
                binding.deployment_id,
                binding.deployment_generation,
                binding.base_url,
            )

        @property
        def route(self) -> ModelEndpointRoute:
            return self._route

        def complete(self, request) -> ModelEndpointResponse:
            return ModelEndpointResponse(
                request_id=request.request.request_id,
                deployment_id=request.deployment_id,
                text="ok",
            )

    binding = _binding(
        latency_isolation_concurrency=1,
        preferred_admitted_concurrency=4,
        max_admitted_concurrency=32,
    )
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)),
        Endpoint,
    )
    for index in range(4):
        result = pool.complete(
            _request(
                f"flow-{index}",
                tenant_id="paper-a",
                lifetime_id=f"life-{index}",
            ),
            {},
            input_tokens=1,
            requested_output_tokens=1,
            timeout_s=2,
        )
        assert result.response.text == "ok"

    snapshot = pool.snapshot()
    assert snapshot.latency_isolation_capacity == 1
    # Preferred concurrency is the adaptive request-window prior, not a
    # persistent lifetime-flow capacity.  Lifetime ownership may coexist up
    # to the measured qualified hard ceiling.
    assert snapshot.persistent_flow_capacity == 32
    assert snapshot.reserved_flow_count == 4
    replica = snapshot.replicas[0]
    assert replica.latency_isolation_concurrency == 1
    assert replica.adaptive_limit == 4
    assert replica.adaptive_max_limit == 32

    fifth = pool.complete(
        _request(
            "flow-4",
            tenant_id="paper-b",
            lifetime_id="life-4",
        ),
        {},
        input_tokens=1,
        requested_output_tokens=1,
        timeout_s=2,
    )
    assert fifth.response.text == "ok"
    assert pool.snapshot().reserved_flow_count == 5

    for index in range(5):
        pool.release_flow(model_lifetime_flow_id(f"life-{index}"))
    pool.close()


def test_preemptive_borrowing_uses_idle_hole_and_protected_return_enters_immediately() -> None:
    entered: list[tuple[str, int | None]] = []
    lock = Lock()
    borrower_entered = Event()
    borrower_gate = Event()

    class Endpoint:
        def __init__(self, binding: QualifiedModelEndpointBinding) -> None:
            self._route = ModelEndpointRoute(
                binding.deployment_id,
                binding.deployment_generation,
                binding.base_url,
            )

        @property
        def route(self) -> ModelEndpointRoute:
            return self._route

        def complete(self, request) -> ModelEndpointResponse:
            priority = request.body.get("priority")
            with lock:
                entered.append((request.request.request_id, priority))
            if request.request.request_id == "B1":
                borrower_entered.set()
                if not borrower_gate.wait(5):
                    raise TimeoutError("borrower gate did not open")
            return ModelEndpointResponse(
                request_id=request.request.request_id,
                deployment_id=request.deployment_id,
                text="ok",
            )

    binding = _binding(
        latency_isolation_concurrency=1,
        max_admitted_concurrency=1,
        preferred_admitted_concurrency=1,
        preemptive_latency_isolation=True,
    )
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)),
        Endpoint,
    )
    pool.complete(
        _request("A1", tenant_id="paper-a", lifetime_id="life-a"),
        {},
        input_tokens=1,
        requested_output_tokens=1,
    )
    assert pool.snapshot().reserved_flow_count == 1

    with ThreadPoolExecutor(max_workers=2) as executor:
        borrower = executor.submit(
            pool.complete,
            _request("B1", tenant_id="paper-b", lifetime_id="life-b"),
            {},
            input_tokens=1,
            requested_output_tokens=1,
            timeout_s=5,
        )
        assert borrower_entered.wait(2)

        returning = executor.submit(
            pool.complete,
            _request("A2", tenant_id="paper-a", lifetime_id="life-a"),
            {},
            input_tokens=1,
            requested_output_tokens=1,
            timeout_s=5,
        )
        assert returning.result(timeout=2).response.text == "ok"
        assert not borrower.done()

        borrower_gate.set()
        assert borrower.result(timeout=2).response.text == "ok"

    priorities = dict(entered)
    assert priorities["B1"] == 1
    assert priorities["A2"] == -1
    runtime = next(iter(pool._runtimes.values()))
    assert runtime.borrowed_in_flight == 0
    assert runtime.in_flight == 0
    assert "life-b" not in {
        value
        for value in pool._flow_owner
    }
    pool.release_flow(model_lifetime_flow_id("life-a"))
    pool.close()


def test_explicit_flow_reservation_is_endpoint_authoritative_per_domain() -> None:
    class Endpoint:
        def __init__(self, binding: QualifiedModelEndpointBinding) -> None:
            self._route = ModelEndpointRoute(
                binding.deployment_id,
                binding.deployment_generation,
                binding.base_url,
            )

        @property
        def route(self) -> ModelEndpointRoute:
            return self._route

        def complete(self, request) -> ModelEndpointResponse:
            return ModelEndpointResponse(
                request_id=request.request.request_id,
                deployment_id=request.deployment_id,
                text="ok",
            )

    binding = _binding(
        latency_isolation_concurrency=1,
        preferred_admitted_concurrency=1,
        max_admitted_concurrency=1,
    )
    first = make_test_model_endpoint_pool(ModelEndpointReplicaSet((binding,)), Endpoint)
    second = make_test_model_endpoint_pool(ModelEndpointReplicaSet((binding,)), Endpoint)
    first.reserve_flow("paper-a", "lifetime:a", deadline=None, cancellation=None)
    assert first.snapshot().reserved_flow_count == 1

    with ThreadPoolExecutor(max_workers=1) as executor:
        waiting = executor.submit(
            first.reserve_flow,
            "paper-b",
            "lifetime:b",
            deadline=Deadline.after(2.0),
            cancellation=None,
        )
        time.sleep(0.05)
        assert not waiting.done()

        # Independent endpoint authorities own independent capacity domains.
        second.reserve_flow(
            "paper-c",
            "lifetime:c",
            deadline=Deadline.after(1.0),
            cancellation=None,
        )
        assert second.snapshot().reserved_flow_count == 1
        first.release_flow("lifetime:a")
        waiting.result(timeout=1.0)

    assert first.snapshot().reserved_flow_count == 1
    first.release_flow("lifetime:b")
    second.release_flow("lifetime:c")
    assert first.snapshot().reserved_flow_count == 0
    assert second.snapshot().reserved_flow_count == 0
    first.close()
    second.close()



def test_explicit_reservation_waiter_cannot_block_reserved_flow_return() -> None:
    class Endpoint:
        def __init__(self, binding: QualifiedModelEndpointBinding) -> None:
            self._route = ModelEndpointRoute(
                binding.deployment_id,
                binding.deployment_generation,
                binding.base_url,
            )

        @property
        def route(self) -> ModelEndpointRoute:
            return self._route

        def complete(self, request) -> ModelEndpointResponse:
            return ModelEndpointResponse(
                request_id=request.request.request_id,
                deployment_id=request.deployment_id,
                text="ok",
            )

    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((_binding(
            latency_isolation_concurrency=1,
            preferred_admitted_concurrency=1,
            max_admitted_concurrency=1,
        ),)),
        Endpoint,
    )
    pool.reserve_flow(
        "paper-a", model_lifetime_flow_id("life-a"),
        deadline=None, cancellation=None,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        queued = executor.submit(
            pool.reserve_flow,
            "paper-b", model_lifetime_flow_id("life-b"),
            deadline=Deadline.after(3.0), cancellation=None,
        )
        time.sleep(0.02)
        assert not queued.done()
        returning = executor.submit(
            pool.complete,
            _request("A2", tenant_id="paper-a", lifetime_id="life-a"),
            {}, input_tokens=1, requested_output_tokens=1,
        )
        assert returning.result(timeout=1.0).response.text == "ok"
        assert not queued.done()
        pool.release_flow(model_lifetime_flow_id("life-a"))
        queued.result(timeout=1.0)
    pool.release_flow(model_lifetime_flow_id("life-b"))
    assert pool.snapshot().reserved_flow_count == 0
    pool.close()


def test_provider_timeout_is_not_a_model_queue_deadline() -> None:
    assert AdaptiveModelEndpointPool._provider_timeout_seconds(None) is None
    assert AdaptiveModelEndpointPool._provider_timeout_seconds(60.0) == 60.0
    assert AdaptiveModelEndpointPool._provider_timeout_seconds(900.0) == 900.0


def test_shared_scheduler_cannot_retire_live_flow_in_other_pool() -> None:
    """One pool releasing a lifetime cannot retire another pool's in-flight flow."""

    class Endpoint:
        def __init__(self, binding: QualifiedModelEndpointBinding) -> None:
            self._route = ModelEndpointRoute(
                binding.deployment_id,
                binding.deployment_generation,
                binding.base_url,
            )

        @property
        def route(self) -> ModelEndpointRoute:
            return self._route

        def complete(self, request) -> ModelEndpointResponse:
            return ModelEndpointResponse(
                request_id=request.request.request_id,
                deployment_id=request.deployment_id,
                text="ok",
            )

    scheduling = UnifiedSchedulingAuthority()
    binding = _binding(latency_isolation_concurrency=1)
    first = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)), Endpoint,
        scheduling_authority=scheduling,
    )
    second = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)), Endpoint,
        scheduling_authority=scheduling,
    )
    flow = model_lifetime_flow_id("life-shared")
    first.reserve_flow("paper", flow, deadline=None, cancellation=None)
    second.reserve_flow("paper", flow, deadline=None, cancellation=None)
    first_flow = first._scheduling_flow_id(flow)
    second_flow = second._scheduling_flow_id(flow)
    assert first_flow != second_flow
    scheduling.record_grant(tenant_id="paper", flow_id=second_flow)
    first.release_flow(flow)
    # On the old unscoped key, release would mark the still-active second
    # physical flow retiring and forbid the next grant in its own pool.
    scheduling.record_grant(tenant_id="paper", flow_id=second_flow)
    assert not scheduling._flow_states[scheduling._flow_key("paper", None, second_flow)].retire_requested
    scheduling.record_completion(
        tenant_id="paper", flow_id=second_flow, service_quanta=1,
    )
    scheduling.record_completion(
        tenant_id="paper", flow_id=second_flow, service_quanta=1,
    )
    second.release_flow(flow)
    assert scheduling._flow_states[scheduling._flow_key("paper", None, second_flow)].retire_requested
    assert first.snapshot().reserved_flow_count == 0
    assert second.snapshot().reserved_flow_count == 0
    first.close()
    second.close()


def test_flow_reservation_cancellation_without_deadline_wakes() -> None:
    import pytest
    from noetrium_platform.foundation.kernel.concurrency.api import TaskCancelled
    from noetrium_platform.foundation.kernel.concurrency.runtime.cancellation import _CancellationState

    class Endpoint:
        def __init__(self, binding):
            self._route = ModelEndpointRoute(
                binding.deployment_id, binding.deployment_generation, binding.base_url
            )
        @property
        def route(self):
            return self._route
        def complete(self, request):
            raise AssertionError("reservation must not dispatch")

    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((
            _binding(
                latency_isolation_concurrency=1,
                preferred_admitted_concurrency=1,
                max_admitted_concurrency=1,
            ),
        )),
        Endpoint,
    )
    pool.reserve_flow("paper-a", "life-a", deadline=None, cancellation=None)
    cancel = _CancellationState()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            pool.reserve_flow, "paper-b", "life-b", deadline=None, cancellation=cancel
        )
        latest = time.monotonic() + 3
        while pool.snapshot().reserved_flow_count != 1 or pool._waiter_count != 1:
            if time.monotonic() >= latest:
                raise AssertionError("second reservation did not queue")
            time.sleep(0.001)
        cancel.cancel("abort waiting lifetime")
        with pytest.raises(TaskCancelled, match="abort waiting lifetime"):
            future.result(timeout=2)
    assert pool.snapshot().reserved_flow_count == 1
    assert pool.snapshot().pending_flow_release_count == 0
    pool.release_flow("life-a")
    pool.close()


def test_rejected_scheduler_model_grant_preserves_local_flow_capacity() -> None:
    import pytest

    class RejectingScheduler(UnifiedSchedulingAuthority):
        def record_grant(self, **kwargs):
            raise RuntimeError("global scheduler refused model grant")

    class Endpoint:
        def __init__(self, binding):
            self._route = ModelEndpointRoute(
                binding.deployment_id, binding.deployment_generation, binding.base_url
            )
        @property
        def route(self):
            return self._route
        def complete(self, request):
            raise AssertionError("no physical dispatch may occur without scheduling grant")

    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((_binding(),)), Endpoint,
        scheduling_authority=RejectingScheduler(),
    )
    with pytest.raises(RuntimeError, match="global scheduler refused model grant"):
        pool.complete(
            _request("rejected", tenant_id="paper", lifetime_id="life-rejected"),
            {}, input_tokens=1, requested_output_tokens=1,
        )
    snapshot = pool.snapshot()
    assert snapshot.active_flow_count == 0
    assert snapshot.reserved_flow_count == 0
    assert snapshot.replicas[0].in_flight == 0
    pool.close()


def test_failed_model_completion_settlement_keeps_local_claim_active() -> None:
    import pytest
    from noetrium_platform.capabilities.model.serving.endpoint.runtime.replica_pool import _FlowAdmissionClass

    class Scheduler(UnifiedSchedulingAuthority):
        reject_completion = False
        def record_completion(self, **kwargs):
            if self.reject_completion:
                raise RuntimeError("injected model completion settlement failure")
            return super().record_completion(**kwargs)

    class Endpoint:
        def __init__(self, binding):
            self._route = ModelEndpointRoute(
                binding.deployment_id, binding.deployment_generation, binding.base_url
            )
        @property
        def route(self):
            return self._route

    scheduler = Scheduler()
    binding = _binding()
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)), Endpoint,
        scheduling_authority=scheduler,
    )
    runtime = pool._runtimes[binding.deployment_id]
    with pool._cv:
        pool._admit_selected_locked(
            owner_id="paper", binding=binding, runtime=runtime,
            prefix_affinity_depth=0, input_tokens=1, requested_output_tokens=1,
            flow_id="life", persistent_flow=True,
        )
    scheduler.reject_completion = True
    completion = dict(
        owner_id="paper", flow_id="life", elapsed_seconds=0.01,
        admission_class=_FlowAdmissionClass.NORMAL, outcome="request_rejected",
        charged_input_tokens=1, reserved_output_tokens=1,
    )
    with pytest.raises(RuntimeError, match="injected model completion settlement"):
        pool._finish(runtime, **completion)
    assert pool.snapshot().replicas[0].in_flight == 1
    assert pool.snapshot().active_flow_count == 1
    assert pool.snapshot().reserved_flow_count == 1
    assert scheduler._flow_states[scheduler._flow_key("paper", None, pool._scheduling_flow_id("life"))].in_flight == 1
    scheduler.reject_completion = False
    pool._finish(runtime, **completion)
    assert pool.snapshot().replicas[0].in_flight == 0
    pool.release_flow("life")
    pool.close()
