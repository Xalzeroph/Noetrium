"""Queue evidence isolates synchronous physical grant critical-path time."""
from __future__ import annotations

import time
from threading import Event, Lock

from tests.model_endpoint_test_support import make_test_model_endpoint_pool
from tests.test_model_endpoint_replica_pool_v1 import (
    _GateEndpoint, _binding, _envelope,
)
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointReplicaSet,
)


def test_slow_global_scheduler_commit_is_measured_as_admission_not_condition_wait(
    monkeypatch,
):
    binding = _binding(0, capacity=2)
    gate = Event()
    gate.set()
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)),
        lambda bound: _GateEndpoint(bound, gate, [], Lock()),
    )
    original = pool._scheduling_authority.record_grant

    def slow_global_commit(**kwargs):
        # Inject artificial durable-writer delay, not a production heuristic.
        time.sleep(.065)
        return original(**kwargs)

    monkeypatch.setattr(pool._scheduling_authority, "record_grant", slow_global_commit)
    try:
        dispatch = pool.complete(
            _envelope(904),
            {"model": "qwen", "messages": [{"role": "user", "content": "x"}]},
            input_tokens=4, requested_output_tokens=2,
        )
        attempt = dispatch.attempts[0]
        assert attempt.queue_admission_wall_seconds >= 0.06
        assert attempt.queue_seconds >= attempt.queue_admission_wall_seconds
        assert "pool_lock_acquisition" in dict(attempt.queue_wait_reason_seconds)
        assert attempt.attempt_digest
        assert attempt.completion_accounting_wall_seconds is not None
        assert attempt.completion_accounting_wall_seconds >= 0
    finally:
        pool.close()


def test_slow_completion_accounting_is_measured_after_model_transport(monkeypatch):
    binding = _binding(0, capacity=2)
    gate = Event()
    gate.set()
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)),
        lambda bound: _GateEndpoint(bound, gate, [], Lock()),
    )
    original = pool._scheduling_authority.record_completion

    def delayed_accounting(**kwargs):
        time.sleep(.045)  # Controlled synthetic durable-writer delay.
        return original(**kwargs)

    monkeypatch.setattr(
        pool._scheduling_authority, "record_completion", delayed_accounting,
    )
    try:
        completed = pool.complete(
            _envelope(905),
            {"model": "qwen", "messages": [{"role": "user", "content": "x"}]},
            input_tokens=4, requested_output_tokens=2,
        )
        attempt = completed.attempts[0]
        assert attempt.completion_accounting_wall_seconds >= .04
        assert attempt.elapsed_seconds < attempt.completion_accounting_wall_seconds
    finally:
        pool.close()


def test_durable_grant_keeps_pool_snapshot_live_and_other_grants_ordered(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as WorkerTimeout
    import pytest

    binding = _binding(0, capacity=2)
    gate = Event()
    gate.set()
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)),
        lambda bound: _GateEndpoint(bound, gate, [], Lock()),
    )
    entered, release = Event(), Event()
    original = pool._scheduling_authority.record_grant
    calls = []

    def controlled_grant(**kwargs):
        calls.append(kwargs['flow_id'])
        if len(calls) == 1:
            entered.set()
            assert release.wait(3), 'held writer did not converge'
        return original(**kwargs)

    monkeypatch.setattr(pool._scheduling_authority, 'record_grant', controlled_grant)
    body = {'model':'qwen','messages':[{'role':'user','content':'hello'}]}
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(pool.complete, _envelope(1940), body,
                               input_tokens=4, requested_output_tokens=2)
        assert entered.wait(2)
        try:
            # Read-only or unrelated model accounting must not be trapped
            # behind a slow global SQLite scheduler COMMIT.
            snap = pool.snapshot()
            assert sum(row.in_flight for row in snap.replicas) == 0
            with pytest.raises(RuntimeError, match='durable scheduling Grant'):
                pool.close()
            second = workers.submit(pool.complete, _envelope(1941), body,
                                    input_tokens=4, requested_output_tokens=2)
            with pytest.raises(WorkerTimeout):
                second.result(timeout=.03)
            assert len(calls) == 1
        finally:
            release.set()
        assert first.result(timeout=2).response.text == 'ok'
        result = second.result(timeout=2)
        assert result.response.text == 'ok'
    assert len(calls) == 2
    assert sum(row.in_flight for row in pool.snapshot().replicas) == 0
    assert pool.snapshot().selection_sequence >= 2
    pool.close()


def test_flow_retirement_waits_for_provisional_durable_grant(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as WorkerTimeout
    from dataclasses import replace
    from noetrium_platform.capabilities.model.request.api import (
        model_request_flow_id, model_request_owner_id,
    )
    from tests.test_model_continuity_claim_outside_pool_lock_v1 import (
        _pool_with_physical_claim,
    )
    import pytest

    pool, registry = _pool_with_physical_claim()
    request = _envelope(1942)
    request = replace(
        request, context=replace(request.context, lifetime_id='pending-grant-life'),
        envelope_digest='',
    )
    flow = model_request_flow_id(request)
    owner = model_request_owner_id(request)
    pool.reserve_flow(owner, flow, deadline=None, cancellation=None)
    entered, release = Event(), Event()
    original = pool._scheduling_authority.record_grant

    def stalled_grant(**kwargs):
        entered.set()
        assert release.wait(3)
        return original(**kwargs)

    monkeypatch.setattr(pool._scheduling_authority, 'record_grant', stalled_grant)
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            pending = workers.submit(
                pool.complete, request,
                {'model':'qwen','messages':[{'role':'user','content':'hello'}]},
                input_tokens=4, requested_output_tokens=2,
            )
            assert entered.wait(2)
            retired = workers.submit(pool.release_flow, flow)
            try:
                with pytest.raises(WorkerTimeout):
                    retired.result(timeout=.025)
                with pool._cv:
                    assert flow in pool._granting_flows
                    assert flow in pool._physical_flow_claims
            finally:
                release.set()
            assert pending.result(timeout=3).response.text == 'ok'
            retired.result(timeout=3)
        assert flow not in pool._physical_flow_claims
        assert flow not in pool._granting_flows
    finally:
        release.set()
        if flow in pool._physical_flow_claims:
            pool.release_flow(flow)
        pool.close()
        registry.close()


def test_failed_durable_global_grant_releases_provisional_local_epoch(monkeypatch):
    import pytest

    binding = _binding(0, capacity=2)
    gate = Event()
    gate.set()
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)),
        lambda bound: _GateEndpoint(bound, gate, [], Lock()),
    )
    original = pool._scheduling_authority.record_grant
    attempts = []

    def injected_failure(**kwargs):
        attempts.append(kwargs['flow_id'])
        if len(attempts) == 1:
            raise PermissionError('authoritative scheduling writer inaccessible')
        return original(**kwargs)

    monkeypatch.setattr(pool._scheduling_authority, 'record_grant', injected_failure)
    body = {'model':'qwen','messages':[{'role':'user','content':'hello'}]}
    try:
        with pytest.raises(PermissionError, match='writer inaccessible'):
            pool.complete(_envelope(1990), body, input_tokens=4)
        with pool._cv:
            assert not pool._global_grant_pending
            assert not pool._granting_flows
            assert sum(row.in_flight for row in pool._runtimes.values()) == 0
        assert pool.complete(
            _envelope(1991), body, input_tokens=4,
        ).response.text == 'ok'
    finally:
        pool.close()



def test_waiter_revalidates_global_grant_after_selection_unlock_window(monkeypatch):
    """A ranking wait/read can return after another waiter began Grant settlement."""
    binding = _binding(0, capacity=2)
    gate = Event()
    gate.set()
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)),
        lambda bound: _GateEndpoint(bound, gate, [], Lock()),
    )
    original_class = pool._flow_admission_class_locked
    class_calls = 0

    def queue_once(flow_id, *, persistent_flow, preemptive_eligible):
        nonlocal class_calls
        class_calls += 1
        if class_calls == 1:
            # Force this request through the waiter path without changing the
            # production capacity algorithm under test.
            return None
        return original_class(
            flow_id,
            persistent_flow=persistent_flow,
            preemptive_eligible=preemptive_eligible,
        )

    selected_calls = 0

    def selected_with_interleaved_grant():
        nonlocal selected_calls
        selected_calls += 1
        waiter = next(iter(pool._waiters_by_ticket.values()))
        if selected_calls == 1:
            # Model the state change that can occur while real waiter ranking
            # has released/waited on the pool mutex.
            pool._global_grant_pending = True
        return waiter

    original_wait = pool._wait_for_waiter_signal_locked
    observed_revalidation = []

    def wait_and_finish_interleaved_grant(waiter, *, timeout_seconds=None, reason="physical_continuity_wait"):
        if reason == "global_scheduling_grant_commit":
            observed_revalidation.append(reason)
            pool._global_grant_pending = False
            return None
        return original_wait(waiter, timeout_seconds=timeout_seconds, reason=reason)

    monkeypatch.setattr(pool, "_flow_admission_class_locked", queue_once)
    monkeypatch.setattr(pool, "_selected_waiter_locked", selected_with_interleaved_grant)
    monkeypatch.setattr(pool, "_wait_for_waiter_signal_locked", wait_and_finish_interleaved_grant)
    try:
        result = pool.complete(
            _envelope(2003),
            {"model": "qwen", "messages": [{"role": "user", "content": "hello"}]},
            input_tokens=4,
            requested_output_tokens=2,
        )
        assert result.response.text == "ok"
        assert observed_revalidation == ["global_scheduling_grant_commit"]
        assert selected_calls >= 2
    finally:
        pool._global_grant_pending = False
        pool.close()
