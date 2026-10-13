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
                request_row["__content_b64"]
            ) == request_wire
            assert base64.b64decode(
                attempt_row["__content_b64"]
            ) == response_wire
            dimensions = attempt_row["__record"]["payload"]["capture"]["dimensions"]
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
                row["idempotency_key"]
                for row in request_rows
            ]
            attempt_event_ids = [
                row["idempotency_key"]
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
                failure = row["payload"]["__record"]["payload"]["capture"]["dimensions"]["failure"]
                assert failure["retryable"] is True
                assert failure["failure_kind"] == "transient"
                assert failure["transport_digest"] == transport_digest
            assert gateway.health().duplicates == 0
            lake.close()
    finally:
        drain_test_concurrency_runtimes()


def test_model_request_and_response_both_fsync_concurrently_on_existing_actors(monkeypatch):
    from threading import Barrier
    from noetrium_platform.evidence.observability.capture.providers.segment_writer import (
        RawSegmentWriter,
    )

    try:
        with tempfile.TemporaryDirectory() as td:
            lake = raw_observation_lake(Path(td))
            gateway = RegistryBoundRawObservationGateway(
                lake, build_default_system_registry(),
            )
            observer = RawLakeModelEndpointObserver(gateway)
            barrier = Barrier(2)
            original = RawSegmentWriter.append_batch
            observed = set()

            def simultaneous_durable_append(writer, rows):
                if writer.family in ('llm.request.raw', 'llm.attempt.raw'):
                    observed.add(writer.family)
                    barrier.wait(timeout=2)
                return original(writer, rows)

            monkeypatch.setattr(
                RawSegmentWriter, 'append_batch', simultaneous_durable_append,
            )
            response = JsonHttpResponse(
                200, {'choices': [{'message': {'content': 'ok'}}]},
                request_body=b'full-model-context', raw_body=b'full-model-output',
            )
            observer.on_exchange(_request('parallel-raw'), response, 11, 22)
            assert observed == {'llm.request.raw', 'llm.attempt.raw'}
            assert not lake.verify('raw-model-run', 'llm.request.raw')
            assert not lake.verify('raw-model-run', 'llm.attempt.raw')
            assert base64.b64decode(
                lake.read('raw-model-run','llm.request.raw')[0]['payload']['__content_b64']
            ) == b'full-model-context'
            assert base64.b64decode(
                lake.read('raw-model-run','llm.attempt.raw')[0]['payload']['__content_b64']
            ) == b'full-model-output'
            lake.close()
    finally:
        drain_test_concurrency_runtimes()


def test_paired_evidence_failure_joins_peer_durable_actor_before_return(monkeypatch):
    import pytest
    from threading import Event
    from noetrium_platform.evidence.observability.capture.providers.segment_writer import (
        RawSegmentWriter,
    )

    try:
        with tempfile.TemporaryDirectory() as td:
            lake = raw_observation_lake(Path(td))
            gateway = RegistryBoundRawObservationGateway(
                lake, build_default_system_registry(),
            )
            observer = RawLakeModelEndpointObserver(gateway)
            original = RawSegmentWriter.append_batch
            response_committed = Event()

            def fail_one_family(writer, rows):
                if writer.family == 'llm.request.raw':
                    raise PermissionError('test request segment unavailable')
                result = original(writer, rows)
                if writer.family == 'llm.attempt.raw':
                    response_committed.set()
                return result

            monkeypatch.setattr(RawSegmentWriter, 'append_batch', fail_one_family)
            with pytest.raises(PermissionError, match='test request segment unavailable'):
                observer.on_exchange(
                    _request('one-segment-fails'),
                    JsonHttpResponse(200, {'choices': [{'message': {'content': 'ok'}}]},
                                     request_body=b'context', raw_body=b'answer'),
                    10, 20,
                )
            assert response_committed.is_set(), 'failed batch returned before peer fsync'
            assert len(lake.read('raw-model-run', 'llm.attempt.raw')) == 1
            assert gateway.health().rejected >= 2
            lake.close()
    finally:
        drain_test_concurrency_runtimes()
