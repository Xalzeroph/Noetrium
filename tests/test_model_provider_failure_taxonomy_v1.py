from __future__ import annotations

from datetime import datetime, timezone

import pytest

from noetrium_platform.capabilities.model.serving.endpoint.api import (
    JsonHttpResponse,
    ModelEndpointError,
)
from noetrium_platform.capabilities.model.serving.provider import (
    ModelProviderFailureKind,
    classify_provider_failure,
    parse_retry_after,
)


def test_retry_after_parses_seconds_and_http_date() -> None:
    assert parse_retry_after("12") == 12.0
    now = datetime(2026, 9, 28, 0, 0, tzinfo=timezone.utc).timestamp()
    assert parse_retry_after(
        "Mon, 28 Sep 2026 00:00:30 GMT",
        now_epoch_s=now,
    ) == 30.0


@pytest.mark.parametrize(
    ("status", "payload", "expected_kind", "retryable", "health"),
    (
        (401, {"error": {"message": "bad key"}}, ModelProviderFailureKind.AUTHENTICATION, False, False),
        (403, {"error": {"message": "forbidden"}}, ModelProviderFailureKind.PERMISSION, False, False),
        (404, {"error": {"message": "missing"}}, ModelProviderFailureKind.NOT_FOUND, False, False),
        (429, {"error": {"message": "slow down"}}, ModelProviderFailureKind.RATE_LIMIT, True, False),
        (503, {"error": {"message": "overloaded"}}, ModelProviderFailureKind.CAPACITY, True, False),
        (500, {"error": {"message": "boom"}}, ModelProviderFailureKind.TRANSIENT, True, True),
        (400, {"error": {"code": "context_length_exceeded", "message": "maximum context"}}, ModelProviderFailureKind.CONTEXT_LIMIT, False, False),
        (400, {"error": {"code": "content_policy_violation", "message": "content policy"}}, ModelProviderFailureKind.CONTENT_FILTER, False, False),
        (400, {"error": {"code": "insufficient_quota", "message": "quota exceeded"}}, ModelProviderFailureKind.QUOTA, False, False),
    ),
)
def test_provider_failure_taxonomy(
    status: int,
    payload: object,
    expected_kind: ModelProviderFailureKind,
    retryable: bool,
    health: bool,
) -> None:
    decision = classify_provider_failure(
        status_code=status,
        payload=payload,
        response_headers=(("retry-after", "7"),) if status == 429 else (),
    )
    assert decision.kind is expected_kind
    assert decision.retryable is retryable
    assert decision.affects_replica_health is health
    assert decision.retry_after_seconds == (7.0 if status == 429 else None)
    assert len(decision.decision_digest) == 64


def test_http_response_preserves_headers_case_insensitively() -> None:
    response = JsonHttpResponse(
        429,
        {"error": {"message": "slow down"}},
        response_headers=(("Retry-After", "9"), ("X-Request-ID", "abc")),
    )
    assert response.response_headers == (
        ("retry-after", "9"),
        ("x-request-id", "abc"),
    )
    assert response.header("RETRY-AFTER") == "9"


def test_endpoint_error_carries_retry_semantics_without_health_poisoning() -> None:
    exc = ModelEndpointError(
        "rate limited",
        status_code=429,
        response_headers=(("Retry-After", "5"),),
        failure_kind="rate_limit",
        retryable=True,
        retry_after_seconds=5,
        provider_code="rate_limit_exceeded",
        affects_replica_health=False,
    )
    assert exc.failure_kind == "rate_limit"
    assert exc.retryable is True
    assert exc.retry_after_seconds == 5.0
    assert exc.affects_replica_health is False
    assert exc.response_headers == (("retry-after", "5"),)
