from __future__ import annotations

import base64
from pathlib import Path
import tempfile

from noetrium_platform.capabilities.model.request.api import ModelRequestEnvelope
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    JsonHttpResponse,
    ModelEndpointError,
    ModelEndpointRequest,
)
from noetrium_platform.composition.model_raw_observation import (
    RawLakeModelEndpointObserver,
)
from noetrium_platform.evidence.artifact.content.api import ArtifactBlobRef
from noetrium_platform.evidence.observability.capture.runtime import (
    RegistryBoundRawObservationGateway,
)
from noetrium_platform.foundation.governance.system_registry.runtime import (
    build_default_system_registry,
)
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    ImmutableModelIdentity,
)
from tests._concurrency_support import (
    drain_test_concurrency_runtimes,
    raw_observation_lake,
)


def _request(request_id: str = "raw-model-request-1") -> ModelEndpointRequest:
    envelope = ModelRequestEnvelope(
        schema_version="model-request.v1",
        request_id=request_id,
        context=ExecutionContext("raw-model-run", "trace", "span"),
        role="planner",
        model=ImmutableModelIdentity(
            "planner",
            "Qwen3-8B",
            "rev",
            "vllm",
            "0.28.0",
            "bfloat16",
            None,
            8192,
        ),
        prompt_generation_id="generation",
        prompt_id="prompt",
        prompt_digest="a" * 64,
        request_body=ArtifactBlobRef(
            "b" * 64,
            2,
            "application/json",
        ),
    )
    return ModelEndpointRequest(
        request=envelope,
        deployment_id="deployment-1",
        deployment_generation="c" * 64,
        body={
            "model": "Qwen3-8B",
            "messages": [{"role": "user", "content": "x"}],
        },
    )


def test_model_raw_observer_persists_exact_success_wire_and_transport_provenance():
    try:
        with tempfile.TemporaryDirectory() as td:
            lake = raw_observation_lake(Path(td))
            gateway = RegistryBoundRawObservationGateway(
                lake,
                build_default_system_registry(),
            )
            observer = RawLakeModelEndpointObserver(gateway)
            request = _request()
            request_wire = b'{"model":"Qwen3-8B","messages":[{"role":"user","content":"x"}]}'
            response_wire = b'{"choices":[{"message":{"content":"ok"}}]}'
            transport_digest = "d" * 64

            observer.on_exchange(
                request,
                JsonHttpResponse(
                    200,
                    {
                        "choices": [
                            {
                                "message": {"content": "ok"},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 3,
                            "completion_tokens": 1,
                        },
                    },
                    raw_body=response_wire,
                    request_body=request_wire,
                    response_headers=(("x-request-id", "provider-1"),),
                    http_version="HTTP/2",
                    transport_digest=transport_digest,
                ),
                10,
                20,
            )

            request_row = lake.read(
                "raw-model-run",
                "llm.request.raw",
            )[0]["payload"]
            attempt_row = lake.read(
                "raw-model-run",
                "llm.attempt.raw",
            )[0]["payload"]

            assert base64.b64decode(
                request_row["__capture"]["raw_payload_b64"]
            ) == request_wire
            assert base64.b64decode(
                attempt_row["__capture"]["raw_payload_b64"]
            ) == response_wire
            dimensions = attempt_row["__capture"]["dimensions"]
            assert dimensions["http_version"] == "HTTP/2"
            assert dimensions["transport_digest"] == transport_digest
            assert dimensions["usage"]["prompt_tokens"] == 3
            assert gateway.health().missing_producers == ()
            lake.close()
    finally:
        drain_test_concurrency_runtimes()


def test_model_raw_observer_allocates_unique_attempts_for_transport_failures():
    try:
        with tempfile.TemporaryDirectory() as td:
            lake = raw_observation_lake(Path(td))
            gateway = RegistryBoundRawObservationGateway(
                lake,
                build_default_system_registry(),
            )
            observer = RawLakeModelEndpointObserver(gateway)
            request = _request("raw-model-retry-1")
            transport_digest = "e" * 64

            for ordinal in (1, 2):
                observer.on_failure(
                    request,
                    ModelEndpointError(
                        f"transport failure {ordinal}",
                        request_body=f"request-{ordinal}".encode(),
                        response_body=f"response-{ordinal}".encode(),
                        failure_kind="transient",
                        retryable=True,
                        affects_replica_health=True,
                        transport_digest=transport_digest,
                    ),
                    ordinal * 10,
                    ordinal * 10 + 5,
                )

            request_rows = lake.read(
                "raw-model-run",
                "llm.request.raw",
            )
            attempt_rows = lake.read(
                "raw-model-run",
                "llm.attempt.raw",
            )
            assert len(request_rows) == 2
            assert len(attempt_rows) == 2
            request_event_ids = [
                row["payload"]["__capture"]["event_id"]
                for row in request_rows
            ]
            attempt_event_ids = [
                row["payload"]["__capture"]["event_id"]
                for row in attempt_rows
            ]
            assert request_event_ids == [
                "raw-model-retry-1:failure:request:1",
                "raw-model-retry-1:failure:request:2",
            ]
            assert attempt_event_ids == [
                "raw-model-retry-1:failure:attempt:1",
                "raw-model-retry-1:failure:attempt:2",
            ]
            for row in attempt_rows:
                failure = row["payload"]["__capture"]["dimensions"]["failure"]
                assert failure["retryable"] is True
                assert failure["failure_kind"] == "transient"
                assert failure["transport_digest"] == transport_digest
            assert gateway.health().duplicates == 0
            lake.close()
    finally:
        drain_test_concurrency_runtimes()
