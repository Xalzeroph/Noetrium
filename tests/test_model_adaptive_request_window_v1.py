from __future__ import annotations

from tests.model_endpoint_test_support import make_test_model_endpoint_pool

from dataclasses import dataclass

import pytest

from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointError,
    ModelEndpointRequest,
    ModelEndpointResponse,
    ModelEndpointRoute,
    ModelRuntimePressureSnapshot,
    OperationalModelEndpointReplica,
    ModelEndpointReplicaSet,
)
from noetrium_platform.capabilities.model.serving.endpoint.runtime import (
    AdaptiveModelEndpointPool,
)
from noetrium_platform.foundation.kernel.kernel import (
    AdaptiveServiceWindow,
    AdaptiveServiceWindowPolicy,
)
from noetrium_platform.capabilities.model.request.api import ModelRequestEnvelope
from noetrium_platform.evidence.artifact.content.api import ArtifactBlobRef
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, ImmutableModelIdentity


class _Clock:
    def __init__(self, value: float = 0.0):
        self.value = value

    def __call__(self) -> float:
        return self.value


def test_adaptive_window_default_start_is_geometric_midpoint():
    clock = _Clock()
    assert AdaptiveServiceWindow(max_limit=1, clock=clock).limit == 1
    assert AdaptiveServiceWindow(max_limit=16, clock=clock).limit == 4
    assert AdaptiveServiceWindow(max_limit=64, clock=clock).limit == 8


def test_adaptive_window_rate_limit_is_minimal_and_transient_does_not_shrink():
    clock = _Clock()
    window = AdaptiveServiceWindow(
        max_limit=20,
        policy=AdaptiveServiceWindowPolicy(min_limit=2, start_limit=10),
        clock=clock,
    )
    window.on_transient_failure()
    assert window.limit == 10
    for _ in range(10):
        window.on_clean_completion()
    assert window.limit == 10
    assert window.snapshot().scale_up_suspended is False
    for _ in range(10):
        window.on_clean_completion()
    assert window.limit == 11
    window.on_pressure(reason="rate_limit")
    assert window.limit == 10
    assert window.snapshot().history[-1].reason == "rate_limit"


def test_adaptive_window_server_queue_uses_observed_service_capacity():
    clock = _Clock()
    window = AdaptiveServiceWindow(
        max_limit=20,
        policy=AdaptiveServiceWindowPolicy(start_limit=12),
        clock=clock,
    )
    window.on_pressure(
        reason="server_queue_pressure",
        observed_capacity=4,
    )
    assert window.limit == 4
    assert window.snapshot().history[-1].reason == "server_queue_pressure"


def test_adaptive_window_preemption_uses_observed_service_capacity():
    clock = _Clock()
    window = AdaptiveServiceWindow(
        max_limit=20,
        policy=AdaptiveServiceWindowPolicy(start_limit=10),
        clock=clock,
    )
    window.on_pressure(
        reason="engine_preemption",
        observed_capacity=6,
    )
    assert window.limit == 6
    assert window.snapshot().history[-1].reason == "engine_preemption"


def test_adaptive_window_throughput_knee_reverts_probe():
    clock = _Clock()
    window = AdaptiveServiceWindow(
        max_limit=8,
        policy=AdaptiveServiceWindowPolicy(start_limit=4),
        clock=clock,
    )
    for _ in range(4):
        window.on_clean_completion(service_seconds_per_item=1.0)
    assert window.limit == 5
    for _ in range(5):
        window.on_clean_completion(service_seconds_per_item=2.0)
    assert window.limit == 4
    assert window.snapshot().history[-1].reason == "throughput_knee"


def test_adaptive_window_history_is_bounded_without_resetting_sequence():
    clock = _Clock(0)
    window = AdaptiveServiceWindow(
        max_limit=2,
        policy=AdaptiveServiceWindowPolicy(min_limit=1, start_limit=2),
        clock=clock,
    )
    for _ in range(300):
        window.on_pressure(reason="capacity_pressure")
        window.on_clean_completion()
        window.on_clean_completion()
        clock.value += 1
    snap = window.snapshot()
    assert len(snap.history) == 256
    assert snap.history[-1].sequence > 256
    assert snap.history[-1].sequence - snap.history[0].sequence == 255


def test_adaptive_window_never_exceeds_qualified_max():
    clock = _Clock(100)
    window = AdaptiveServiceWindow(
        max_limit=3,
        policy=AdaptiveServiceWindowPolicy(min_limit=1, start_limit=10),
        clock=clock,
    )
    assert window.limit == 3
    for _ in range(20):
        window.on_clean_completion()
    assert window.limit == 3


@dataclass
class _Endpoint:
    route: ModelEndpointRoute
    outcomes: list[str]

    def complete(self, request: ModelEndpointRequest) -> ModelEndpointResponse:
        outcome = self.outcomes.pop(0) if self.outcomes else "ok"
        if outcome == "rate":
            raise ModelEndpointError(
                "rate",
                status_code=429,
                failure_kind="rate_limit",
                retryable=True,
                affects_replica_health=False,
            )
        if outcome == "transient":
            raise ModelEndpointError(
                "transient",
                status_code=500,
                failure_kind="transient",
                retryable=True,
                affects_replica_health=True,
            )
        return ModelEndpointResponse(
            request_id=request.request.request_id,
            deployment_id=request.deployment_id,
            text="ok",
            input_tokens=1,
            output_tokens=1,
        )


def _request() -> ModelRequestEnvelope:
    return ModelRequestEnvelope(
        schema_version="model-request.v1",
        request_id="r-1",
        context=ExecutionContext("run", "trace", "span"),
        role="planner",
        model=ImmutableModelIdentity(
            "planner", "model", "rev", "vllm", "1", "bf16", None, 4096
        ),
        prompt_generation_id="g",
        prompt_id="p",
        prompt_digest="a" * 64,
        request_body=ArtifactBlobRef("b" * 64, 2, "application/json"),
    )


def test_pool_rate_limit_changes_effective_window_but_not_qualified_capacity():
    clock = _Clock(0)
    route = ModelEndpointRoute("dep", "c" * 64, "http://127.0.0.1:1")
    replica = OperationalModelEndpointReplica(route, capacity=10)
    endpoint = _Endpoint(route, ["rate", "ok"])
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((replica,)),
        lambda _binding: endpoint,
        adaptive_window_policy=AdaptiveServiceWindowPolicy(
            min_limit=1, start_limit=10
        ),
        clock=clock,
    )
    with pytest.raises(ModelEndpointError):
        pool.complete(
            _request(),
            {"model": "model", "messages": [{"role": "user", "content": "x"}]},
        )
    snap = pool.snapshot().replicas[0]
    assert snap.capacity == 10
    assert snap.adaptive_limit == 9
    assert snap.failures == 0
    assert snap.request_rejections == 1
    assert snap.adaptive_window_history[-1][3] == "rate_limit"


def test_pool_transient_failure_does_not_shrink_adaptive_window():
    clock = _Clock(0)
    route = ModelEndpointRoute("dep", "d" * 64, "http://127.0.0.1:1")
    replica = OperationalModelEndpointReplica(route, capacity=10)
    endpoint = _Endpoint(route, ["transient"])
    pool = make_test_model_endpoint_pool(
        ModelEndpointReplicaSet((replica,)),
        lambda _binding: endpoint,
        adaptive_window_policy=AdaptiveServiceWindowPolicy(
            min_limit=1, start_limit=8
        ),
        clock=clock,
    )
    with pytest.raises(ModelEndpointError):
        pool.complete(
            _request(),
            {"model": "model", "messages": [{"role": "user", "content": "x"}]},
        )
    snap = pool.snapshot().replicas[0]
    assert snap.adaptive_limit == 8
    assert snap.failures == 1
    assert snap.adaptive_scale_up_suspended is True


def test_large_qualified_window_probes_only_one_concurrency_at_a_time() -> None:
    clock = _Clock(0)
    window = AdaptiveServiceWindow(
        max_limit=1024,
        policy=AdaptiveServiceWindowPolicy(min_limit=1, start_limit=512),
        clock=clock,
    )
    for _ in range(512):
        window.on_clean_completion()
    assert window.limit == 513
    assert window.snapshot().history[-1].reason == "clean_completion"
