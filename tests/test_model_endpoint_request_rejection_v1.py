from __future__ import annotations

import pytest

from noetrium_platform.capabilities.model.request.api import ModelRequestEnvelope
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointRequestRejected,
    ModelEndpointReplicaSet,
    ModelEndpointResponse,
    ModelEndpointRoute,
    OperationalModelEndpointReplica,
)
from noetrium_platform.capabilities.model.serving.endpoint.runtime import (
    AdaptiveModelEndpointPool,
)
from noetrium_platform.evidence.artifact.content.api import ArtifactBlobRef
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    ImmutableModelIdentity,
)


def _envelope(index: int) -> ModelRequestEnvelope:
    return ModelRequestEnvelope(
        schema_version="model-request.v1",
        request_id=f"request-{index}",
        context=ExecutionContext(f"run-{index}", f"trace-{index}", f"span-{index}"),
        role="planner",
        model=ImmutableModelIdentity(
            "planner", "qwen", "a" * 64, "vllm", "0.13.0",
            "bfloat16", None, 8192,
        ),
        prompt_generation_id="prompt-v1",
        prompt_id="planner",
        prompt_digest="b" * 64,
        request_body=ArtifactBlobRef("c" * 64, 2, "application/json"),
    )


class _RejectThenSucceedEndpoint:
    def __init__(self, replica: OperationalModelEndpointReplica) -> None:
        self.route = replica.route
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        if self.calls == 1:
            raise ModelEndpointRequestRejected(
                "HTTP 400 request rejected",
                status_code=400,
                request_body=b"{}",
                response_body=b'{"error":{"message":"invalid seed"}}',
            )
        return ModelEndpointResponse(
            request_id=request.request.request_id,
            deployment_id=request.deployment_id,
            text="ok",
        )


def test_request_rejection_does_not_poison_replica_health() -> None:
    replica = OperationalModelEndpointReplica(
        ModelEndpointRoute("replica-0", "d" * 64, "http://127.0.0.1:18000"),
        1,
    )
    endpoint = _RejectThenSucceedEndpoint(replica)
    pool = AdaptiveModelEndpointPool(
        ModelEndpointReplicaSet((replica,)),
        lambda _binding: endpoint,
        failure_cooldown_seconds=60,
        max_failure_cooldown_seconds=60,
    )

    with pytest.raises(ModelEndpointRequestRejected):
        pool.complete(_envelope(0), {"model": "qwen"})

    after_rejection = pool.snapshot().replicas[0]
    assert after_rejection.request_rejections == 1
    assert after_rejection.failures == 0
    assert after_rejection.consecutive_failures == 0
    assert after_rejection.cooling_down is False
    assert after_rejection.completed == 0

    result = pool.complete(_envelope(1), {"model": "qwen"})
    assert result.response.text == "ok"
    final = pool.snapshot().replicas[0]
    assert final.completed == 1
    assert final.request_rejections == 1
    assert final.failures == 0
