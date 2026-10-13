"""Durable VTC completion settles off the pool lock without early capacity release."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from tests.model_endpoint_test_support import make_test_model_endpoint_pool
from tests.test_model_endpoint_replica_pool_v1 import _binding, _envelope
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointReplicaSet, ModelEndpointResponse, ModelEndpointRoute,
)


def test_durable_completion_does_not_block_independent_admissible_flow(monkeypatch):
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

    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)),
        lambda _binding: Endpoint(),
    )
    entered, allow_first = Event(), Event()
    original = pool._scheduling_authority.record_completion

    def held_writer(**kwargs):
        if not entered.is_set():
            entered.set()
            assert allow_first.wait(3), "delayed writer did not converge"
        return original(**kwargs)

    monkeypatch.setattr(pool._scheduling_authority, "record_completion", held_writer)
    body = {"model": "qwen", "messages": [
        {"role": "user", "content": "hello"},
    ]}
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            pool.complete, _envelope(1), body, input_tokens=3,
            requested_output_tokens=2,
        )
        assert entered.wait(2)
        # The first physical permit remains occupied while its SQLite
        # completion is delayed. The other qualified permit must be usable.
        assert sum(replica.in_flight for replica in pool.snapshot().replicas) == 1
        second = executor.submit(
            pool.complete, _envelope(2), body, input_tokens=3,
            requested_output_tokens=2,
        )
        try:
            assert second.result(timeout=1.5).response.text == "ok"
            assert sum(replica.in_flight for replica in pool.snapshot().replicas) == 1
        finally:
            allow_first.set()
        assert first.result(timeout=2).response.text == "ok"
    assert sum(replica.in_flight for replica in pool.snapshot().replicas) == 0
    pool.close()


def test_overlapping_completions_preserve_exact_durable_service_count(monkeypatch, tmp_path):
    from threading import Barrier
    from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import (
        DurableUnifiedSchedulingAuthority,
    )
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

    scheduler = DurableUnifiedSchedulingAuthority(tmp_path / "scheduler.sqlite")
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((binding,)),
        lambda _binding: Endpoint(),
        scheduling_authority=scheduler,
    )
    original = pool._scheduling_authority.record_completion
    barrier = Barrier(2)

    def concurrent_commit(**kwargs):
        # Both physical calls must be able to reach the durable settlement
        # boundary simultaneously, but SQLite serializes their real commits.
        barrier.wait(timeout=3)
        return original(**kwargs)

    monkeypatch.setattr(pool._scheduling_authority, "record_completion", concurrent_commit)
    body = {"model": "qwen", "messages": [
        {"role": "user", "content": "hello"},
    ]}
    with ThreadPoolExecutor(max_workers=2) as workers:
        left = workers.submit(
            pool.complete, _envelope(4), body,
            input_tokens=3, requested_output_tokens=1,
        )
        right = workers.submit(
            pool.complete, _envelope(5), body,
            input_tokens=3, requested_output_tokens=1,
        )
        assert left.result(timeout=4).response.text == "ok"
        assert right.result(timeout=4).response.text == "ok"
    assert sum(row.in_flight for row in pool.snapshot().replicas) == 0
    assert sum(row.completed for row in pool.snapshot().replicas) == 2
    pool.close()
    scheduler.close()
