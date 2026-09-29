from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import pytest

from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointReplicaSet,
    ModelEndpointRoute,
    OperationalModelEndpointReplica,
)
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.foundation.kernel.concurrency.api import (
    ExecutionLaneKind,
    ExecutionSpec,
    TaskFailureScope,
)
from noetrium_platform.infrastructure.resources.compute.providers import (
    LocalHostRuntimeObserver,
)


class _ObservedResource:
    def __init__(self, pool: ResearchExecutionPool, *, fail_first: bool = False) -> None:
        self.pool = pool
        self.fail_first = fail_first
        self.close_calls = 0
        self.model_domain_closed_during_close: list[bool] = []

    def close(self) -> None:
        self.close_calls += 1
        self.model_domain_closed_during_close.append(
            self.pool._model_io.topology_snapshot().closed
        )
        if self.fail_first and self.close_calls == 1:
            raise RuntimeError("synthetic resource close failure")


def _pool() -> ResearchExecutionPool:
    return ResearchExecutionPool(
        host_runtime_observer=LocalHostRuntimeObserver(),
    )


def test_research_execution_pool_closes_model_resources_before_model_io_domain():
    pool = _pool()
    resource = _ObservedResource(pool)
    pool.register_model_io_resource(resource)

    pool.close()

    assert resource.close_calls == 1
    assert resource.model_domain_closed_during_close == [False]
    topology = pool._model_io.topology_snapshot()
    assert topology.closed is True
    assert topology.converged is True


def test_failed_model_resource_close_preserves_model_io_for_retry():
    pool = _pool()
    resource = _ObservedResource(pool, fail_first=True)
    pool.register_model_io_resource(resource)

    with pytest.raises(ExceptionGroup, match="research execution pool close failed"):
        pool.close()

    assert resource.close_calls == 1
    assert resource.model_domain_closed_during_close == [False]
    first = pool._model_io.topology_snapshot()
    assert first.closed is False
    assert first.converged is False

    pool.close()

    assert resource.close_calls == 2
    assert resource.model_domain_closed_during_close == [False, False]
    second = pool._model_io.topology_snapshot()
    assert second.closed is True
    assert second.converged is True



class _BaseExceptionOnceResource(_ObservedResource):
    def close(self) -> None:
        self.close_calls += 1
        self.model_domain_closed_during_close.append(
            self.pool._model_io.topology_snapshot().closed
        )
        if self.close_calls == 1:
            raise KeyboardInterrupt("synthetic base-exception close failure")


def test_base_exception_model_resource_close_is_preserved_for_retry():
    pool = _pool()
    resource = _BaseExceptionOnceResource(pool)
    pool.register_model_io_resource(resource)

    with pytest.raises(
        BaseExceptionGroup,
        match="research execution pool close failed",
    ) as captured:
        pool.close()

    assert "KeyboardInterrupt" in repr(captured.value)
    assert resource.close_calls == 1
    assert pool._model_io.topology_snapshot().closed is False

    pool.close()

    assert resource.close_calls == 2
    assert pool._model_io.topology_snapshot().closed is True


def test_quiesce_closes_request_model_io_resources_before_domain():
    pool = _pool()
    resource = _ObservedResource(pool)
    pool.register_model_io_resource(resource)

    pool.quiesce_workloads()

    assert resource.close_calls == 1
    assert resource.model_domain_closed_during_close == [False]
    assert pool._model_io.topology_snapshot().closed is True
    assert pool._model_io.topology_snapshot().converged is True

    pool.close()
    assert resource.close_calls == 1


def test_physical_model_lifecycle_resource_survives_quiesce_until_terminal_close():
    pool = _pool()
    resource = _ObservedResource(pool)
    pool.register_model_lifecycle_resource(resource)

    pool.quiesce_workloads()

    assert resource.close_calls == 0
    assert pool._model_io.topology_snapshot().closed is True

    pool.close()

    assert resource.close_calls == 1
    assert resource.model_domain_closed_during_close == [True]


class _SharedTransportObserver:
    def __init__(self, pool: ResearchExecutionPool) -> None:
        self.pool = pool
        self.owner_closed_during_close: list[bool] = []

    def close(self) -> None:
        owner = self.pool._model_http_transport_owner
        assert owner is not None
        self.owner_closed_during_close.append(owner.closed)


def test_research_execution_pool_reuses_one_model_http_transport_and_closes_it_last():
    pool = _pool()
    first = pool.model_http_transport
    second = pool.model_http_transport
    assert first is second

    owner = pool._model_http_transport_owner
    assert owner is not None
    assert owner.closed is False

    borrower = _SharedTransportObserver(pool)
    pool.register_model_io_resource(borrower)
    pool.close()

    assert borrower.owner_closed_during_close == [False]
    assert owner.closed is True

def test_shared_model_http_transport_closes_on_its_bound_model_io_loop():
    pool = _pool()
    transport = pool.model_http_transport
    owner = pool._model_http_transport_owner
    assert owner is not None
    borrower = pool.open_model_io_group("bind-shared-http-loop")

    async def bind(context):
        context.checkpoint()
        transport._bind_loop()
        context.checkpoint()

    handle = borrower.submit(
        ExecutionSpec(
            task_id="bind-shared-http-loop",
            lane_kind=ExecutionLaneKind.ASYNC_IO,
            failure_scope=TaskFailureScope.CALLER,
        ),
        bind,
    )
    handle.result(timeout=5.0)

    pool.quiesce_workloads()

    assert owner.closed is True
    assert pool._model_io.topology_snapshot().closed is True
    assert pool._model_io.topology_snapshot().converged is True
    pool.close()


def test_research_execution_pool_reuses_exact_model_endpoint_pool_across_trials():
    pool = _pool()
    replica_set = ModelEndpointReplicaSet(
        (
            OperationalModelEndpointReplica(
                ModelEndpointRoute(
                    "shared-model",
                    "a" * 64,
                    "http://127.0.0.1:18080",
                ),
                4,
            ),
        )
    )
    observer = object()

    first = pool.model_endpoint_pool(replica_set, observers=(observer,))
    second = pool.model_endpoint_pool(replica_set, observers=(observer,))

    assert first is second
    assert len(pool._model_endpoint_pools) == 1

    isolated = pool.model_endpoint_pool(replica_set, observers=(object(),))
    assert isolated is not first
    assert len(pool._model_endpoint_pools) == 2

    pool.close()


def test_research_execution_pool_single_flights_concurrent_endpoint_pool_materialization():
    pool = _pool()
    replica_set = ModelEndpointReplicaSet(
        (
            OperationalModelEndpointReplica(
                ModelEndpointRoute(
                    "shared-model-concurrent",
                    "b" * 64,
                    "http://127.0.0.1:18081",
                ),
                8,
            ),
        )
    )
    observer = object()

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [
            executor.submit(
                pool.model_endpoint_pool,
                replica_set,
                observers=(observer,),
            )
            for _ in range(16)
        ]
        resolved = [future.result(timeout=5) for future in futures]

    assert all(item is resolved[0] for item in resolved)
    assert len(pool._model_endpoint_pools) == 1
    pool.close()


def test_research_execution_pool_reuses_structured_model_json_http_client():
    pool = _pool()
    transport = pool.model_http_transport
    first = pool.model_json_http_client
    second = pool.model_json_http_client

    assert first is second
    assert first._transport is transport

    pool.close()
