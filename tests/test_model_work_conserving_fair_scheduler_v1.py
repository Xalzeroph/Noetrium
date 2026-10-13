"""Work-conserving selection keeps the original fair ordering and affine pinning."""
from __future__ import annotations

from threading import Event, Lock
from concurrent.futures import ThreadPoolExecutor, TimeoutError as WorkerTimeout

import pytest

from tests.model_endpoint_test_support import make_test_model_endpoint_pool
from tests.test_model_endpoint_replica_pool_v1 import (
    _GateEndpoint, _binding, _envelope,
)
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointReplicaSet,
)
from noetrium_platform.capabilities.model.serving.endpoint.runtime.replica_pool import (
    _PoolWaiter,
)


def test_pinned_blocked_fair_head_cannot_idle_a_free_replica():
    bindings = (_binding(0, capacity=1), _binding(1, capacity=2))
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet(bindings),
        lambda binding: _GateEndpoint(binding, Event(), [], Lock()),
    )
    # Synthetic immutable scheduling cut: existing protected flow pinned to
    # replica 0 while replica 1 has qualified physical request capacity.
    with pool._cv:
        pool._runtimes["replica-0"].in_flight = 1
        pool._reserved_flows.add("pinned-flow")
        pool._physical_flow_claims["pinned-flow"] = (
            "replica-0", object(),
        )
        head = _PoolWaiter(
            pool._next_waiter_ticket, "pinned-owner", pool._clock(),
            "pinned-flow", True, None, 1.0,
            dispatch_input_token_ids=(), dispatch_input_tokens=4,
            dispatch_preemptive_eligible=True,
        )
        pool._next_waiter_ticket += 1
        pool._enqueue_waiter_locked(head)
        assert pool._dispatch_waiter_feasible_locked(head) is False
        # Fair priority remains higher even though it cannot run.
        assert pool._selected_waiter_locked() is None

        other = _PoolWaiter(
            pool._next_waiter_ticket, "free-owner", pool._clock(),
            "free-flow", False, None, 1.0,
            dispatch_input_token_ids=(), dispatch_input_tokens=4,
            dispatch_preemptive_eligible=True,
        )
        pool._next_waiter_ticket += 1
        pool._enqueue_waiter_locked(other)
        assert pool._selected_waiter_locked() is other
        assert other.diagnostics.bypassed_ineligible_heads == 1

        # Once replica 0 is physically free again, the protected waiter
        # takes its original entitlement ahead of the later unpinned flow.
        pool._runtimes["replica-0"].in_flight = 0
        pool._notify_selected_waiter_locked()
        assert pool._selected_waiter_locked() is head

        pool._remove_waiter_locked(other)
        pool._remove_waiter_locked(head)
        pool._reserved_flows.clear()
        pool._physical_flow_claims.clear()
    pool.close()


def test_model_dispatch_evidence_has_bounded_queue_reasons_and_no_fabricated_wait():
    binding = _binding(0, capacity=2)
    entered = []
    gate = Event()
    gate.set()
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)),
        lambda row: _GateEndpoint(row, gate, entered, Lock()),
    )
    try:
        result = pool.complete(
            _envelope(513), {"model": "qwen", "messages": [
                {"role": "user", "content": "hello"}
            ]}, input_tokens=5, requested_output_tokens=1,
        )
        attempt = result.attempts[0]
        # Even the fast path accounts for the actual pool lock acquisition;
        # its finite nanosecond cost must not be mislabeled as GPU queue time.
        assert dict(attempt.queue_wait_reason_seconds)["pool_lock_acquisition"] >= 0.0
        assert attempt.queue_bypassed_ineligible_heads == 0
        assert attempt.queue_seconds >= 0
    finally:
        pool.close()


def test_real_queue_wait_records_replica_capacity_duration():
    from noetrium_platform.capabilities.model.serving.endpoint.api import (
        ModelEndpointResponse, ModelEndpointRoute,
    )
    binding = _binding(0, capacity=1)
    entered, release = Event(), Event()

    class HeldEndpoint:
        route = ModelEndpointRoute(
            binding.deployment_id, binding.deployment_generation,
            binding.base_url,
        )
        def complete(self, request):
            if request.request.request_id == "request-1":
                entered.set()
                assert release.wait(3)
            return ModelEndpointResponse(
                request_id=request.request.request_id,
                deployment_id=request.deployment_id,
                text="ok",
            )

    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)),
        lambda _binding: HeldEndpoint(),
    )
    body = {"model": "qwen", "messages": [
        {"role": "user", "content": "hello"}
    ]}
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(
            pool.complete, _envelope(1), body,
            input_tokens=5, requested_output_tokens=1,
        )
        assert entered.wait(2)
        second = workers.submit(
            pool.complete, _envelope(2), body,
            input_tokens=5, requested_output_tokens=1,
        )
        try:
            with pytest.raises(WorkerTimeout):
                second.result(timeout=.05)
        finally:
            release.set()
        assert first.result(timeout=2).response.text == "ok"
        result = second.result(timeout=2)
    attempt = result.attempts[0]
    by_reason = dict(attempt.queue_wait_reason_seconds)
    # The pool's flow reservation is the first rejected admission boundary;
    # don't falsely attribute it to HTTP/GPU execution pressure.
    assert by_reason.get("flow_reservation_capacity", 0.0) > 0
    assert sum(by_reason.values()) <= attempt.queue_seconds
    assert attempt.queue_bypassed_ineligible_heads == 0
    pool.close()


def test_real_call_bypasses_a_pinned_blocked_head_without_misrouting_it():
    bindings = (_binding(0, capacity=1), _binding(1, capacity=2))
    enter, release = Event(), Event()
    release.set()
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet(bindings),
        lambda binding: _GateEndpoint(binding, release, [], Lock()),
    )
    with pool._cv:
        pool._runtimes["replica-0"].in_flight = 1
        pool._reserved_flows.add("pinned-flow")
        pool._physical_flow_claims["pinned-flow"] = ("replica-0", object())
        head = _PoolWaiter(
            pool._next_waiter_ticket, "blocked-owner", pool._clock(),
            "pinned-flow", True, None, 1.0,
            dispatch_input_token_ids=(), dispatch_input_tokens=5,
            dispatch_preemptive_eligible=True,
        )
        pool._next_waiter_ticket += 1
        pool._enqueue_waiter_locked(head)
        assert pool._selected_waiter_locked() is None
        assert pool._waiter_block_reason_locked(head) == "pinned_replica_concurrency"
        fair_credit_before = dict(pool._owner_worker_credit_quanta)
        pool._selected_waiter_locked()
        assert pool._owner_worker_credit_quanta == fair_credit_before
    try:
        result = pool.complete(
            _envelope(712), {
                "model": "qwen",
                "messages": [{"role": "user", "content": "ready"}],
            }, input_tokens=5, requested_output_tokens=1,
        )
        assert result.response.deployment_id == "replica-1"
        assert result.attempts[0].queue_bypassed_ineligible_heads >= 1
        assert result.attempts[0].queue_seconds >= 0
    finally:
        with pool._cv:
            pool._remove_waiter_locked(head)
            pool._runtimes["replica-0"].in_flight = 0
            pool._reserved_flows.clear()
            pool._physical_flow_claims.clear()
        pool.close()


def test_denied_physical_reservation_does_not_block_until_authority_epoch_changes():
    bindings = (_binding(0, capacity=1), _binding(1, capacity=1))
    gate = Event()
    gate.set()
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet(bindings),
        lambda binding: _GateEndpoint(binding, gate, [], Lock()),
    )
    with pool._cv:
        reservation = _PoolWaiter(
            pool._next_waiter_ticket, "reservation-owner", pool._clock(),
            "reserve-one", True, None, 0.0,
        )
        pool._next_waiter_ticket += 1
        pool._enqueue_waiter_locked(reservation)
        reservation.diagnostics.physically_denied_epoch = (
            pool._physical_capacity_epoch
        )
        dispatch = _PoolWaiter(
            pool._next_waiter_ticket, "dispatch-owner", pool._clock(),
            "dispatch-one", False, None, 1.0,
            dispatch_input_token_ids=(), dispatch_input_tokens=5,
            dispatch_preemptive_eligible=True,
        )
        pool._next_waiter_ticket += 1
        pool._enqueue_waiter_locked(dispatch)
        assert pool._selected_waiter_locked() is dispatch
        assert dispatch.diagnostics.bypassed_ineligible_heads > 0

        pool._physical_capacity_epoch += 1
        pool._notify_selected_waiter_locked()
        assert pool._dispatch_waiter_feasible_locked(reservation)
        assert pool._selected_waiter_locked() is reservation

        pool._remove_waiter_locked(reservation)
        pool._remove_waiter_locked(dispatch)
    pool.close()


def test_pool_lock_contention_is_not_misclassified_as_model_capacity():
    import time
    from threading import Thread
    from noetrium_platform.capabilities.model.serving.endpoint.api import (
        ModelEndpointResponse, ModelEndpointRoute,
    )

    binding = _binding(0, capacity=2)
    class InstantEndpoint:
        route = ModelEndpointRoute(
            binding.deployment_id, binding.deployment_generation,
            binding.base_url,
        )
        def complete(self, request):
            return ModelEndpointResponse(
                request_id=request.request.request_id,
                deployment_id=request.deployment_id,
                text="ok",
            )

    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)),
        lambda _binding: InstantEndpoint(),
    )
    entered = Event()
    result_holder = []
    def client():
        entered.set()
        result_holder.append(pool.complete(
            _envelope(907), {"model": "qwen", "messages": [
                {"role": "user", "content": "hello"},
            ]}, input_tokens=5, requested_output_tokens=1,
        ))

    worker = Thread(target=client)
    try:
        with pool._cv:
            worker.start()
            assert entered.wait(2)
            # This is a controlled test hold, not a production polling loop.
            time.sleep(.08)
        worker.join(timeout=4)
        assert not worker.is_alive()
        attempt = result_holder[0].attempts[0]
        reasons = dict(attempt.queue_wait_reason_seconds)
        assert reasons["pool_lock_acquisition"] >= .05
        assert "flow_reservation_capacity" not in reasons
        assert sum(reasons.values()) <= attempt.queue_seconds
    finally:
        worker.join(timeout=4)
        pool.close()


def test_feasibility_proof_does_not_search_prefix_cache_or_mutate_virtual_service():
    from unittest.mock import patch
    bindings = (_binding(0, capacity=1), _binding(1, capacity=1))
    gate = Event()
    gate.set()
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet(bindings),
        lambda binding: _GateEndpoint(binding, gate, [], Lock()),
    )
    with pool._cv:
        before = dict(pool._owner_worker_credit_quanta)
        waiter = _PoolWaiter(
            pool._next_waiter_ticket, "prefix-independent", pool._clock(),
            "prefix-independent", False, None, 1.0,
            dispatch_input_token_ids=tuple(range(8192)),
            dispatch_input_tokens=2048, dispatch_output_tokens=256,
            dispatch_preemptive_eligible=True,
        )
        with patch.object(
            type(pool), "_longest_prefix_workers_locked",
            side_effect=AssertionError(
                "eligibility probe cannot run complete prefix routing"
            ),
        ):
            assert pool._dispatch_waiter_feasible_locked(waiter)
        assert dict(pool._owner_worker_credit_quanta) == before
    pool.close()


def test_lightweight_eligibility_matches_full_route_for_capacity_state_cuts():
    bindings = (_binding(0, capacity=2), _binding(1, capacity=2))
    gate = Event()
    gate.set()
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet(bindings),
        lambda binding: _GateEndpoint(binding, gate, [], Lock()),
    )
    from itertools import product
    with pool._cv:
        for busy_0, busy_1, cooling_0, cooling_1 in product(
            range(3), range(3), (False, True), (False, True),
        ):
            a = pool._runtimes["replica-0"]
            b = pool._runtimes["replica-1"]
            a.in_flight, b.in_flight = busy_0, busy_1
            a.cooldown_until = (
                pool._clock()+100 if cooling_0 else 0
            )
            b.cooldown_until = (
                pool._clock()+100 if cooling_1 else 0
            )
            owner = "feasibility-owner"
            flow = "capacity-flow"
            waiter = _PoolWaiter(
                0, owner, pool._clock(),
                flow, False, None, 1.0,
                dispatch_input_token_ids=tuple(range(512)),
                dispatch_input_tokens=512, dispatch_output_tokens=32,
                dispatch_preemptive_eligible=True,
            )
            cls = pool._flow_admission_class_locked(
                flow, persistent_flow=False, preemptive_eligible=True
            )
            full = (
                cls is not None
                and pool._selection_candidate_locked(
                    waiter.dispatch_input_token_ids,
                    frozenset(), 512, 32,
                    owner_id=owner, admission_class=cls, probe_only=True,
                )[1] is not None
            )
            light = pool._dispatch_waiter_feasible_locked(waiter)
            assert light is full, (busy_0,busy_1,cooling_0,cooling_1)
        a.in_flight=b.in_flight=0
        a.cooldown_until=b.cooldown_until=0
    pool.close()
