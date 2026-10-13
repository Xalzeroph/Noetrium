from __future__ import annotations

from threading import Event, Thread

from tests.model_endpoint_test_support import make_test_model_endpoint_pool
from tests.test_model_endpoint_replica_pool_v1 import _CapacityEndpoint, _binding
from noetrium_platform.capabilities.model.serving.endpoint.api import ModelEndpointReplicaSet
from noetrium_platform.capabilities.model.serving.endpoint.runtime.replica_pool import _PoolWaiter
from noetrium_platform.foundation.kernel.concurrency.scheduling.runtime import UnifiedSchedulingAuthority


class _CountingScheduling(UnifiedSchedulingAuthority):
    def __init__(self) -> None:
        super().__init__()
        self.single_calls = 0
        self.batch_calls = 0
        self.batch_sizes: list[int] = []

    def ordering_key(self, candidate, *, now_monotonic):
        self.single_calls += 1
        return super().ordering_key(candidate, now_monotonic=now_monotonic)

    def ordering_keys(self, candidates, *, now_monotonic):
        self.batch_calls += 1
        self.batch_sizes.append(len(candidates))
        return super().ordering_keys(candidates, now_monotonic=now_monotonic)


def test_model_waiter_ranking_projects_one_coherent_authority_batch() -> None:
    scheduling = _CountingScheduling()
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((_binding(0, capacity=1),)),
        _CapacityEndpoint,
        scheduling_authority=scheduling,
    )
    try:
        with pool._cv:
            for index in range(128):
                pool._enqueue_waiter_locked(
                    _PoolWaiter(index, f"owner-{index}", float(index))
                )
            selected = pool._selected_waiter_locked()
            assert selected is not None
            assert scheduling.batch_calls == 1
            assert scheduling.batch_sizes == [128]
            assert scheduling.single_calls == 0
    finally:
        pool.close()


class _StalledBatchScheduling(UnifiedSchedulingAuthority):
    def __init__(self) -> None:
        super().__init__()
        self.entered = Event()
        self.release = Event()

    def ordering_keys(self, candidates, *, now_monotonic):
        self.entered.set()
        assert self.release.wait(3.0)
        return super().ordering_keys(candidates, now_monotonic=now_monotonic)


def test_durable_ranking_wait_never_holds_replica_pool_mutex() -> None:
    scheduling = _StalledBatchScheduling()
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((_binding(0, capacity=1),)),
        _CapacityEndpoint,
        scheduling_authority=scheduling,
    )
    result: list[_PoolWaiter | None] = []

    with pool._cv:
        waiter = _PoolWaiter(1, "owner", 0.0)
        pool._enqueue_waiter_locked(waiter)

    def select() -> None:
        with pool._cv:
            result.append(pool._selected_waiter_locked())

    thread = Thread(target=select, daemon=True)
    thread.start()
    try:
        assert scheduling.entered.wait(2.0)
        # The ranking thread is blocked beyond the Scheduling Authority boundary.
        # Replica completion/admission/retirement must still be able to enter the
        # pool immediately instead of convoying behind that durable read.
        assert pool._lock.acquire(timeout=0.2)
        pool._lock.release()
    finally:
        scheduling.release.set()
        thread.join(3.0)
        pool.close()
    assert not thread.is_alive()
    assert result == [waiter]


def test_local_ranking_inputs_are_reused_but_remote_service_is_always_fresh(monkeypatch):
    scheduling = _CountingScheduling()
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((_binding(0, capacity=1),)), _CapacityEndpoint,
        scheduling_authority=scheduling,
    )
    builds = 0
    original = pool._scheduling_candidate_locked

    def counted(waiter):
        nonlocal builds
        builds += 1
        return original(waiter)

    monkeypatch.setattr(pool, '_scheduling_candidate_locked', counted)
    try:
        with pool._cv:
            first = _PoolWaiter(0, 'owner-0', 0.0)
            second = _PoolWaiter(1, 'owner-1', 1.0)
            pool._enqueue_waiter_locked(first)
            pool._enqueue_waiter_locked(second)
            assert pool._selected_waiter_locked() is first
            for _ in range(10):
                assert pool._selected_waiter_locked() is first
            assert builds == 2
        scheduling.record_grant(tenant_id='owner-0', flow_id=pool._scheduling_flow_id('owner-0'))
        scheduling.record_completion(tenant_id='owner-0', flow_id=pool._scheduling_flow_id('owner-0'), service_quanta=100)
        with pool._cv:
            assert pool._selected_waiter_locked() is second
            assert builds == 2, 'global service refresh must not rebuild local immutable candidates'
            pool._remove_waiter_locked(first)
            assert pool._waiter_input_projection is None
            assert pool._selected_waiter_locked() is second
            assert builds == 3
    finally:
        pool.close()
