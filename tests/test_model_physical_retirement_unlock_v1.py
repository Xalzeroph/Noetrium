"""Physical continuity settlement never monopolizes the shared model pool mutex."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as WorkerTimeout
from threading import Event
from types import SimpleNamespace

import pytest

from tests.model_endpoint_test_support import make_test_model_endpoint_pool
from tests.test_model_endpoint_replica_pool_v1 import _binding, _envelope
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointReplicaSet, ModelEndpointResponse, ModelEndpointRoute,
)
from noetrium_platform.capabilities.model.serving.endpoint.runtime import (
    ModelEndpointPoolUnavailable,
)


def _pool():
    binding = _binding(0, capacity=2)

    class Endpoint:
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

    return make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)), lambda _binding: Endpoint(),
    )


def test_slow_authority_release_does_not_hold_model_pool_lock_or_block_other_owner():
    pool = _pool()
    pool.reserve_flow("owner-one", "life-one", deadline=None, cancellation=None)
    entered, release = Event(), Event()
    calls = []

    def slow_release():
        calls.append("release")
        entered.set()
        assert release.wait(3), "test release gate timed out"

    with pool._cv:
        pool._physical_flow_claims["life-one"] = ("replica-0", SimpleNamespace(release=slow_release))

    with ThreadPoolExecutor(max_workers=3) as workers:
        retire = workers.submit(pool.release_flow, "life-one")
        assert entered.wait(2)
        # A physical commit is in flight but an unrelated request must still
        # be able to use the genuinely free certified model capacity.
        other = workers.submit(
            pool.complete, _envelope(871),
            {"model": "qwen", "messages": [{"role": "user", "content": "next"}]},
            input_tokens=3, requested_output_tokens=1,
        )
        retry = workers.submit(pool.release_flow, "life-one")
        try:
            assert other.result(timeout=1.5).response.text == "ok"
            assert pool.snapshot().reserved_flow_count == 1
            with pytest.raises(ModelEndpointPoolUnavailable, match="retiring"):
                pool.reserve_flow("owner-one", "life-one", deadline=None, cancellation=None)
            with pytest.raises(WorkerTimeout):
                retry.result(timeout=.025)
        finally:
            release.set()
        retire.result(timeout=2)
        retry.result(timeout=2)
    assert calls == ["release"]
    assert pool.snapshot().reserved_flow_count == 0
    pool.close()


def test_failed_authority_retirement_preserves_exact_claim_for_retry():
    pool = _pool()
    pool.reserve_flow("owner-one", "life-one", deadline=None, cancellation=None)
    calls = []

    def transient_release():
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError("authority writer unavailable")

    with pool._cv:
        physical = ("replica-0", SimpleNamespace(release=transient_release))
        pool._physical_flow_claims["life-one"] = physical
    with pytest.raises(PermissionError, match="authority writer unavailable"):
        pool.release_flow("life-one")
    with pool._cv:
        assert pool._physical_flow_claims["life-one"] is physical
        assert "life-one" in pool._reserved_flows
        assert "life-one" in pool._pending_flow_releases
        assert "life-one" not in pool._retiring_flow_releases
    pool.release_flow("life-one")
    assert len(calls) == 2
    assert pool.snapshot().reserved_flow_count == 0
    pool.close()


def test_slow_terminal_physical_release_does_not_hold_scheduler_lock():
    pool = _pool()
    pool.reserve_flow("owner", "flow:terminal", deadline=None, cancellation=None)
    entered, release = Event(), Event()
    calls = []
    def slow_release():
        calls.append(1)
        entered.set()
        assert release.wait(3)
    with pool._cv:
        pool._physical_flow_claims["flow:terminal"] = (
            "replica-0", SimpleNamespace(release=slow_release),
        )
    with ThreadPoolExecutor(max_workers=2) as workers:
        closing = workers.submit(pool.close)
        assert entered.wait(2)
        try:
            # An independent ASYNC_IO callback can still acquire this lock
            # while durable close effects are ongoing. Pool admits no new
            # model work because the terminal admission cut is already set.
            assert pool._cv.acquire(timeout=.3)
            pool._cv.release()
            with pytest.raises(ModelEndpointPoolUnavailable):
                pool.complete(
                    _envelope(901),
                    {"model": "qwen", "messages": [
                        {"role": "user", "content": "denied"}
                    ]}, input_tokens=2, requested_output_tokens=1,
                )
            duplicate = workers.submit(pool.close)
            with pytest.raises(WorkerTimeout):
                duplicate.result(timeout=.025)
        finally:
            release.set()
        closing.result(timeout=2)
        duplicate.result(timeout=2)
    assert calls == [1]
    assert pool._terminal_close_complete
    assert not pool._physical_flow_claims


def test_terminal_claim_release_failure_is_recoverable_without_losing_identity():
    pool = _pool()
    pool.reserve_flow("owner", "flow:retry-close", deadline=None, cancellation=None)
    calls = []
    def release():
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError("Authority unavailable")
    physical = ("replica-0", SimpleNamespace(release=release))
    with pool._cv:
        pool._physical_flow_claims["flow:retry-close"] = physical
    with pytest.raises(BaseExceptionGroup, match="physical retirement failed"):
        pool.close()
    with pool._cv:
        assert pool._closed
        assert pool._physical_flow_claims["flow:retry-close"] is physical
        assert "flow:retry-close" in pool._reserved_flows
        assert "flow:retry-close" in pool._pending_flow_releases
    pool.close()
    assert calls == [1, 1]
    assert pool._terminal_close_complete
