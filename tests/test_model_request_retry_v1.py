from __future__ import annotations

from dataclasses import dataclass

import pytest

from noetrium_platform.capabilities.model.request.api import ModelRequestEnvelope
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointError,
    ModelEndpointRequest,
    ModelEndpointResponse,
    ModelEndpointRoute,
    ModelEndpointReplicaSet,
    OperationalModelEndpointReplica,
)
from noetrium_platform.capabilities.model.serving.endpoint.runtime import (
    AdaptiveModelEndpointPool,
    AdaptiveRequestWindowPolicy,
    ModelRequestRetryPolicy,
)
from noetrium_platform.evidence.artifact.content.api import ArtifactBlobRef
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    ImmutableModelIdentity,
)


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0
    def __call__(self) -> float:
        return self.value
    def sleep(self, seconds: float) -> None:
        self.value += seconds


@dataclass
class _Endpoint:
    route: ModelEndpointRoute
    outcomes: list[str]

    def complete(self, request: ModelEndpointRequest) -> ModelEndpointResponse:
        outcome = self.outcomes.pop(0) if self.outcomes else "ok"
        if outcome == "rate":
            raise ModelEndpointError(
                "rate limited",
                status_code=429,
                failure_kind="rate_limit",
                retryable=True,
                retry_after_seconds=3.0,
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
        if outcome == "invalid":
            raise ModelEndpointError(
                "invalid",
                status_code=400,
                failure_kind="invalid_request",
                retryable=False,
                affects_replica_health=False,
            )
        return ModelEndpointResponse(
            request_id=request.request.request_id,
            deployment_id=request.deployment_id,
            text="ok",
            input_tokens=1,
            output_tokens=1,
        )


def _request(request_id: str = "retry-r1") -> ModelRequestEnvelope:
    return ModelRequestEnvelope(
        schema_version="model-request.v1",
        request_id=request_id,
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


def _body():
    return {"model":"model","messages":[{"role":"user","content":"x"}]}


def test_default_retry_policy_is_single_attempt_and_attaches_failure_receipt():
    clock=_Clock()
    route=ModelEndpointRoute("dep","c"*64,"http://127.0.0.1:1")
    replica=OperationalModelEndpointReplica(route,capacity=8)
    endpoint=_Endpoint(route,["rate","ok"])
    pool=AdaptiveModelEndpointPool(
        ModelEndpointReplicaSet((replica,)),
        lambda _:endpoint,
        clock=clock,
        sleep=clock.sleep,
    )

    with pytest.raises(ModelEndpointError) as caught:
        pool.complete(_request(),_body())

    exc=caught.value
    assert len(exc.dispatch_attempts)==1
    assert exc.dispatch_attempts[0].failure_kind=="rate_limit"
    assert exc.dispatch_attempts[0].wait_before_next_seconds==0.0
    assert len(endpoint.outcomes)==1
    assert len(exc.retry_policy_digest)==64


def test_explicit_rate_limit_retry_honors_retry_after_and_records_attempts():
    clock=_Clock()
    route=ModelEndpointRoute("dep","d"*64,"http://127.0.0.1:1")
    replica=OperationalModelEndpointReplica(route,capacity=10)
    endpoint=_Endpoint(route,["rate","ok"])
    pool=AdaptiveModelEndpointPool(
        ModelEndpointReplicaSet((replica,)),
        lambda _:endpoint,
        retry_policy=ModelRequestRetryPolicy(max_attempts=2),
        adaptive_window_policy=AdaptiveRequestWindowPolicy(
            min_limit=1,start_limit=10,decrease_factor=0.5,
            scale_up_percent=0.2,cooldown_seconds=10,
        ),
        clock=clock,
        sleep=clock.sleep,
    )

    result=pool.complete(_request(),_body())

    assert len(result.attempts)==2
    assert result.attempts[0].outcome=="request_rejected"
    assert result.attempts[0].failure_kind=="rate_limit"
    assert result.attempts[0].wait_before_next_seconds==3.0
    assert result.attempts[1].outcome=="completed"
    assert clock.value==3.0
    snap=pool.snapshot().replicas[0]
    assert snap.capacity==10
    assert snap.adaptive_limit==5
    assert snap.failures==0
    assert snap.request_rejections==1


def test_transient_retry_moves_to_other_replica_without_shrinking_window():
    clock=_Clock()
    route_a=ModelEndpointRoute("dep-a","e"*64,"http://127.0.0.1:1")
    route_b=ModelEndpointRoute("dep-b","f"*64,"http://127.0.0.1:2")
    replica_a=OperationalModelEndpointReplica(route_a,capacity=8)
    replica_b=OperationalModelEndpointReplica(route_b,capacity=8)
    endpoint_a=_Endpoint(route_a,["transient"])
    endpoint_b=_Endpoint(route_b,["ok"])
    endpoints={"dep-a":endpoint_a,"dep-b":endpoint_b}
    pool=AdaptiveModelEndpointPool(
        ModelEndpointReplicaSet((replica_a,replica_b)),
        lambda binding:endpoints[binding.deployment_id],
        retry_policy=ModelRequestRetryPolicy(
            max_attempts=2,
            base_backoff_seconds=0.0,
            max_backoff_seconds=0.0,
        ),
        adaptive_window_policy=AdaptiveRequestWindowPolicy(
            min_limit=1,start_limit=8,cooldown_seconds=10,
        ),
        clock=clock,
        sleep=clock.sleep,
    )

    result=pool.complete(_request(),_body())

    assert [a.deployment_id for a in result.attempts]==["dep-a","dep-b"]
    assert result.attempts[0].failure_kind=="transient"
    snaps={row.deployment_id:row for row in pool.snapshot().replicas}
    assert snaps["dep-a"].adaptive_limit==8
    assert snaps["dep-a"].adaptive_scale_up_suspended is True
    assert snaps["dep-a"].failures==1


def test_non_retryable_request_is_never_replayed_even_with_retry_budget():
    clock=_Clock()
    route=ModelEndpointRoute("dep","1"*64,"http://127.0.0.1:1")
    replica=OperationalModelEndpointReplica(route,capacity=4)
    endpoint=_Endpoint(route,["invalid","ok"])
    pool=AdaptiveModelEndpointPool(
        ModelEndpointReplicaSet((replica,)),
        lambda _:endpoint,
        retry_policy=ModelRequestRetryPolicy(max_attempts=3),
        clock=clock,
        sleep=clock.sleep,
    )

    with pytest.raises(ModelEndpointError) as caught:
        pool.complete(_request(),_body())

    assert len(caught.value.dispatch_attempts)==1
    assert caught.value.dispatch_attempts[0].failure_kind=="invalid_request"
    assert len(endpoint.outcomes)==1


def test_exhausted_retry_preserves_complete_attempt_history():
    clock=_Clock()
    route=ModelEndpointRoute("dep","2"*64,"http://127.0.0.1:1")
    replica=OperationalModelEndpointReplica(route,capacity=8)
    endpoint=_Endpoint(route,["rate","rate"])
    pool=AdaptiveModelEndpointPool(
        ModelEndpointReplicaSet((replica,)),
        lambda _:endpoint,
        retry_policy=ModelRequestRetryPolicy(
            max_attempts=2,
            honor_retry_after=False,
            base_backoff_seconds=1.0,
            max_backoff_seconds=1.0,
        ),
        clock=clock,
        sleep=clock.sleep,
    )

    with pytest.raises(ModelEndpointError) as caught:
        pool.complete(_request(),_body())

    attempts=caught.value.dispatch_attempts
    assert len(attempts)==2
    assert [row.attempt_number for row in attempts]==[1,2]
    assert attempts[0].wait_before_next_seconds==1.0
    assert attempts[1].wait_before_next_seconds==0.0
    assert len({row.attempt_digest for row in attempts})==2

def test_rate_limit_retry_prefers_unattempted_interchangeable_replica():
    clock=_Clock()
    route_a=ModelEndpointRoute("dep-a","3"*64,"http://127.0.0.1:1")
    route_b=ModelEndpointRoute("dep-b","4"*64,"http://127.0.0.1:2")
    replica_a=OperationalModelEndpointReplica(route_a,capacity=8)
    replica_b=OperationalModelEndpointReplica(route_b,capacity=8)
    endpoint_a=_Endpoint(route_a,["rate"])
    endpoint_b=_Endpoint(route_b,["ok"])
    endpoints={"dep-a":endpoint_a,"dep-b":endpoint_b}
    pool=AdaptiveModelEndpointPool(
        ModelEndpointReplicaSet((replica_a,replica_b)),
        lambda binding:endpoints[binding.deployment_id],
        retry_policy=ModelRequestRetryPolicy(
            max_attempts=2,
            honor_retry_after=False,
            base_backoff_seconds=0.0,
            max_backoff_seconds=0.0,
        ),
        clock=clock,
        sleep=clock.sleep,
    )

    result=pool.complete(_request("retry-diversity"),_body())

    assert [row.deployment_id for row in result.attempts] == ["dep-a","dep-b"]
    assert result.attempts[0].failure_kind == "rate_limit"
    assert result.response.deployment_id == "dep-b"
