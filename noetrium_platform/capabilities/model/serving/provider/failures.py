from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
import math
import time

from noetrium_platform.foundation.kernel.kernel import canonical_digest


class ModelProviderFailureKind(str, Enum):
    INVALID_REQUEST = "invalid_request"
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    NOT_FOUND = "not_found"
    RATE_LIMIT = "rate_limit"
    QUOTA = "quota"
    CONTEXT_LIMIT = "context_limit"
    CONTENT_FILTER = "content_filter"
    CAPACITY = "capacity"
    TIMEOUT = "timeout"
    TRANSIENT = "transient"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ModelProviderFailureDecision:
    kind: ModelProviderFailureKind
    retryable: bool
    affects_replica_health: bool
    retry_after_seconds: float | None = None
    provider_code: str | None = None
    provider_message: str | None = None
    decision_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ModelProviderFailureKind):
            raise TypeError("provider failure kind is invalid")
        if type(self.retryable) is not bool or type(self.affects_replica_health) is not bool:
            raise TypeError("provider failure decision booleans are invalid")
        if self.retry_after_seconds is not None:
            value = self.retry_after_seconds
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0
            ):
                raise ValueError("provider retry_after_seconds must be finite and non-negative")
            object.__setattr__(self, "retry_after_seconds", float(value))
        for name in ("provider_code", "provider_message"):
            value = getattr(self, name)
            if value is not None and (type(value) is not str or not value.strip()):
                raise ValueError(f"{name} must be non-empty text or None")
        object.__setattr__(
            self,
            "decision_digest",
            canonical_digest(
                {
                    "schema": "noetrium.model-provider-failure-decision.v1",
                    "kind": self.kind.value,
                    "retryable": self.retryable,
                    "affects_replica_health": self.affects_replica_health,
                    "retry_after_seconds": self.retry_after_seconds,
                    "provider_code": self.provider_code,
                    "provider_message": self.provider_message,
                }
            ),
        )


def _header_value(
    headers: tuple[tuple[str, str], ...],
    name: str,
) -> str | None:
    target = name.lower()
    for key, value in headers:
        if key.lower() == target:
            return value
    return None


def parse_retry_after(
    value: str | None,
    *,
    now_epoch_s: float | None = None,
    max_seconds: float = 24 * 60 * 60,
) -> float | None:
    if value is None:
        return None
    if type(value) is not str or not value.strip():
        return None
    if (
        isinstance(max_seconds, bool)
        or not isinstance(max_seconds, (int, float))
        or not math.isfinite(float(max_seconds))
        or float(max_seconds) <= 0
    ):
        raise ValueError("max_seconds must be finite and positive")
    text = value.strip()
    try:
        seconds = float(text)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        now = float(time.time() if now_epoch_s is None else now_epoch_s)
        seconds = parsed.timestamp() - now
    if not math.isfinite(seconds):
        return None
    return min(float(max_seconds), max(0.0, seconds))


def _provider_error_fields(payload: object) -> tuple[str | None, str | None]:
    current = payload
    if isinstance(current, Mapping) and isinstance(current.get("error"), Mapping):
        current = current["error"]
    if not isinstance(current, Mapping):
        return None, None
    code = None
    for key in ("code", "type", "status", "error_code"):
        value = current.get(key)
        if isinstance(value, str) and value.strip():
            code = value.strip()
            break
    message = None
    for key in ("message", "detail", "error_description"):
        value = current.get(key)
        if isinstance(value, str) and value.strip():
            message = value.strip()[:2048]
            break
    return code, message


def classify_provider_failure(
    *,
    status_code: int,
    payload: object,
    response_headers: tuple[tuple[str, str], ...] = (),
    now_epoch_s: float | None = None,
) -> ModelProviderFailureDecision:
    if type(status_code) is not int or not 100 <= status_code <= 599:
        raise ValueError("provider status_code must be an HTTP status")
    if type(response_headers) is not tuple or any(
        type(row) is not tuple
        or len(row) != 2
        or any(type(value) is not str or not value for value in row)
        for row in response_headers
    ):
        raise TypeError("provider response_headers must be text pairs")

    code, message = _provider_error_fields(payload)
    haystack = " ".join(
        part.lower()
        for part in (code or "", message or "")
        if part
    )
    retry_after = parse_retry_after(
        _header_value(response_headers, "retry-after"),
        now_epoch_s=now_epoch_s,
    )

    if any(token in haystack for token in (
        "context_length", "context length", "maximum context", "max context",
        "too many tokens", "prompt is too long", "input is too long",
    )):
        kind = ModelProviderFailureKind.CONTEXT_LIMIT
    elif any(token in haystack for token in (
        "content_policy", "content policy", "content_filter", "safety",
        "blocked for safety", "moderation",
    )):
        kind = ModelProviderFailureKind.CONTENT_FILTER
    elif any(token in haystack for token in (
        "insufficient_quota", "quota exceeded", "quota_exceeded",
        "billing hard limit", "billing_hard_limit",
    )):
        kind = ModelProviderFailureKind.QUOTA
    elif status_code == 401:
        kind = ModelProviderFailureKind.AUTHENTICATION
    elif status_code == 403:
        kind = ModelProviderFailureKind.PERMISSION
    elif status_code == 404:
        kind = ModelProviderFailureKind.NOT_FOUND
    elif status_code == 429:
        kind = ModelProviderFailureKind.RATE_LIMIT
    elif status_code in {408, 504}:
        kind = ModelProviderFailureKind.TIMEOUT
    elif status_code in {503, 529} or any(
        token in haystack for token in ("overloaded", "capacity", "server busy")
    ):
        kind = ModelProviderFailureKind.CAPACITY
    elif 500 <= status_code <= 599:
        kind = ModelProviderFailureKind.TRANSIENT
    elif status_code in {400, 409, 413, 422}:
        kind = ModelProviderFailureKind.INVALID_REQUEST
    else:
        kind = ModelProviderFailureKind.UNKNOWN

    retryable = kind in {
        ModelProviderFailureKind.RATE_LIMIT,
        ModelProviderFailureKind.CAPACITY,
        ModelProviderFailureKind.TIMEOUT,
        ModelProviderFailureKind.TRANSIENT,
    }
    affects_replica_health = kind in {
        ModelProviderFailureKind.TIMEOUT,
        ModelProviderFailureKind.TRANSIENT,
        ModelProviderFailureKind.INTERNAL,
        ModelProviderFailureKind.UNKNOWN,
    }
    return ModelProviderFailureDecision(
        kind=kind,
        retryable=retryable,
        affects_replica_health=affects_replica_health,
        retry_after_seconds=retry_after,
        provider_code=code,
        provider_message=message,
    )


__all__ = [
    "ModelProviderFailureDecision",
    "ModelProviderFailureKind",
    "classify_provider_failure",
    "parse_retry_after",
]
