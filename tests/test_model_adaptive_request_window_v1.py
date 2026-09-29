from __future__ import annotations

from dataclasses import dataclass

import pytest

from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointError,
    ModelEndpointRequest,
    ModelEndpointResponse,
    ModelEndpointRoute,
    OperationalModelEndpointReplica,
    ModelEndpointReplicaSet,
)
from noetrium_platform.capabilities.model.serving.endpoint.runtime import (
    AdaptiveModelEndpointPool,
    AdaptiveRequestWindow,
    AdaptiveRequestWindowPolicy,
)
from noetrium_platform.capabilities.model.request.api import ModelRequestEnvelope
from noetrium_platform.evidence.artifact.content.api import ArtifactBlobRef
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, ImmutableModelIdentity


class _Clock:
    def __init__(self, value: float = 0.0):
        self.value = value
    def __call__(self) -> float:
        return self.value


def test_adaptive_window_rate_limit_reduces_and_transient_does_not():
    clock=_Clock()
    window=AdaptiveRequestWindow(
        max_limit=20,
        policy=AdaptiveRequestWindowPolicy(
            min_limit=2,
            start_limit=10,
            decrease_factor=0.5,
            scale_up_percent=0.2,
            cooldown_seconds=10,
        ),
        clock=clock,
    )
    assert window.limit == 10
    window.on_transient_failure()
    assert window.limit == 10
    clock.value = 11
    for _ in range(10):
        window.on_clean_completion()
    assert window.limit == 12
    window.on_rate_limit()
    assert window.limit == 6
    snap=window.snapshot()
    assert [event.reason for event in snap.history] == ["clean_completion","rate_limit"]
    assert snap.max_limit == 20


def test_adaptive_window_never_exceeds_qualified_max():
    clock=_Clock(100)
    window=AdaptiveRequestWindow(
        max_limit=3,
        policy=AdaptiveRequestWindowPolicy(
            min_limit=1,
            start_limit=10,
            scale_up_percent=1.0,
            cooldown_seconds=0,
        ),
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
        outcome=self.outcomes.pop(0) if self.outcomes else "ok"
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
        context=ExecutionContext("run","trace","span"),
        role="planner",
        model=ImmutableModelIdentity(
            "planner","model","rev","vllm","1","bf16",None,4096
        ),
        prompt_generation_id="g",
        prompt_id="p",
        prompt_digest="a"*64,
        request_body=ArtifactBlobRef("b"*64,2,"application/json"),
    )


def test_pool_rate_limit_changes_effective_window_but_not_qualified_capacity():
    clock=_Clock(0)
    route=ModelEndpointRoute("dep","c"*64,"http://127.0.0.1:1")
    replica=OperationalModelEndpointReplica(route,capacity=10)
    endpoint=_Endpoint(route,["rate","ok"])

    pool=AdaptiveModelEndpointPool(
        ModelEndpointReplicaSet((replica,)),
        lambda _binding:endpoint,
        adaptive_window_policy=AdaptiveRequestWindowPolicy(
            min_limit=1,start_limit=10,decrease_factor=0.5,
            scale_up_percent=0.2,cooldown_seconds=10,
        ),
        clock=clock,
    )

    with pytest.raises(ModelEndpointError):
        pool.complete(_request(),{"model":"model","messages":[{"role":"user","content":"x"}]})

    snap=pool.snapshot().replicas[0]
    assert snap.capacity == 10
    assert snap.adaptive_limit == 5
    assert snap.failures == 0
    assert snap.request_rejections == 1
    assert snap.adaptive_window_history[-1][3] == "rate_limit"


def test_pool_transient_failure_does_not_shrink_adaptive_window():
    clock=_Clock(0)
    route=ModelEndpointRoute("dep","d"*64,"http://127.0.0.1:1")
    replica=OperationalModelEndpointReplica(route,capacity=10)
    endpoint=_Endpoint(route,["transient"])

    pool=AdaptiveModelEndpointPool(
        ModelEndpointReplicaSet((replica,)),
        lambda _binding:endpoint,
        adaptive_window_policy=AdaptiveRequestWindowPolicy(
            min_limit=1,start_limit=8,cooldown_seconds=10,
        ),
        clock=clock,
    )
    with pytest.raises(ModelEndpointError):
        pool.complete(_request(),{"model":"model","messages":[{"role":"user","content":"x"}]})
    snap=pool.snapshot().replicas[0]
    assert snap.adaptive_limit == 8
    assert snap.failures == 1
    assert snap.adaptive_scale_up_suspended is True
