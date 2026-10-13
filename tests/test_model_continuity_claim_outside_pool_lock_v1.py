"""Durable physical admission cannot hold the global model scheduling mutex."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as WorkerTimeout
from threading import Event, Lock
from unittest.mock import patch

import pytest

from model_admission_test_support import make_model_admission_registry
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointReplicaSet,
)
from tests.model_endpoint_test_support import make_test_model_endpoint_pool
from tests.test_model_endpoint_replica_pool_v1 import (
    _GateEndpoint, _binding, _envelope,
)


def _pool_with_physical_claim():
    binding = _binding(0, capacity=2)
    registry = make_model_admission_registry()
    controller = registry.controller_for(
        deployment_id=binding.deployment_id,
        deployment_generation=binding.deployment_generation,
        qualified_capacity=2,
        continuity_capacity=1,
    )
    ready = Event()
    ready.set()
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)),
        lambda member: _GateEndpoint(member, ready, [], Lock()),
        physical_continuity_controllers={binding.deployment_id: controller},
    )
    return pool, registry


def test_slow_durable_claim_does_not_hold_queue_lock_or_hide_independent_work():
    pool, registry = _pool_with_physical_claim()
    entered, continue_claim = Event(), Event()
    original = type(pool)._acquire_physical_flow_claim

    def slow_claim(self, *, owner_id, flow_id):
        entered.set()
        assert continue_claim.wait(3)
        return original(self, owner_id=owner_id, flow_id=flow_id)

    with patch.object(type(pool), "_acquire_physical_flow_claim", slow_claim):
        with ThreadPoolExecutor(max_workers=3) as workers:
            pending = workers.submit(
                pool.reserve_flow,
                "paper-a", "flow:claim-in-progress",
                deadline=None, cancellation=None,
            )
            assert entered.wait(2)
            try:
                # Closing during an outstanding physical effect must fail
                # closed instead of returning with an invisible durable Claim.
                with pytest.raises(RuntimeError, match="during physical Claim"):
                    pool.close()
                independent = workers.submit(
                    pool.complete,
                    _envelope(1432),
                    {
                        "model": "qwen",
                        "messages": [{"role": "user", "content": "unrelated"}],
                    },
                    input_tokens=8,
                    requested_output_tokens=1,
                )
                assert independent.result(timeout=1).response.text == "ok"
                # Flow retirement must await this exact pending Claim's
                # publication, never silently conclude there is nothing held.
                retire = workers.submit(
                    pool.release_flow, "flow:claim-in-progress"
                )
                with pytest.raises(WorkerTimeout):
                    retire.result(timeout=.025)
            finally:
                continue_claim.set()
            pending.result(timeout=3)
            retire.result(timeout=3)
    assert "flow:claim-in-progress" not in pool._physical_flow_claims
    assert "flow:claim-in-progress" not in pool._reserved_flows
    assert not pool._claiming_flows
    pool.close()
    registry.close()


def test_failed_physical_claim_does_not_poison_other_owners():
    pool, registry = _pool_with_physical_claim()

    def rejected(self, *, owner_id, flow_id):
        raise RuntimeError("Resource Authority rejected Claim")

    with patch.object(type(pool), "_acquire_physical_flow_claim", rejected):
        with pytest.raises(RuntimeError, match="Authority rejected Claim"):
            pool.reserve_flow(
                "paper-a", "flow:failing",
                deadline=None, cancellation=None,
            )
    assert not pool._claiming_flows
    assert "flow:failing" not in pool._physical_flow_claims
    result = pool.complete(
        _envelope(7325),
        {
            "model": "qwen",
            "messages": [{"role": "user", "content": "ready"}],
        },
        input_tokens=3, requested_output_tokens=1,
    )
    assert result.response.text == "ok"
    pool.close()
    registry.close()


def test_deadline_expiring_during_physical_commit_rolls_back_without_leak():
    from noetrium_platform.foundation.kernel.concurrency.api import Deadline
    pool, registry = _pool_with_physical_claim()
    entered, continue_claim = Event(), Event()
    original = type(pool)._acquire_physical_flow_claim

    def delayed_commit(self, *, owner_id, flow_id):
        entered.set()
        assert continue_claim.wait(3)
        return original(self, owner_id=owner_id, flow_id=flow_id)

    with patch.object(type(pool), "_acquire_physical_flow_claim", delayed_commit):
        with ThreadPoolExecutor(max_workers=1) as workers:
            pending = workers.submit(
                pool.reserve_flow, "paper-deadline", "flow:expired-during-io",
                deadline=Deadline.after(.06), cancellation=None,
            )
            assert entered.wait(2)
            try:
                with pytest.raises(WorkerTimeout):
                    pending.result(timeout=.11)
            finally:
                continue_claim.set()
            with pytest.raises(TimeoutError, match="after deadline"):
                pending.result(timeout=3)
    assert "flow:expired-during-io" not in pool._physical_flow_claims
    assert "flow:expired-during-io" not in pool._reserved_flows
    assert not pool._claiming_flows
    pool.close()
    registry.close()
