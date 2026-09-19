from __future__ import annotations

import re
from collections.abc import Mapping

_SENSITIVE_KEYS = frozenset({
    "authorization", "api_key", "apikey", "token", "access_token", "refresh_token",
    "password", "passwd", "secret", "client_secret", "cookie", "set-cookie",
    "private_key", "credential", "credentials",
})

_PATTERNS = (
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+\-/=]{8,}"), r"\1<REDACTED>"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"), "<REDACTED>"),
    (re.compile(r"\bhf_[A-Za-z0-9]{8,}\b"), "<REDACTED>"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{8,}\b"), "<REDACTED>"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{8,}\b"), "<REDACTED>"),
    (re.compile(r"\bAKIA[A-Z0-9]{12,}\b"), "<REDACTED>"),
    (re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b"), "<REDACTED>"),
    (re.compile(r"(?i)((?:api[_-]?key|token|password|passwd|secret|client[_-]?secret|authorization)\s*[=:]\s*)[^\s,;]+"), r"\1<REDACTED>"),
    (re.compile(r"(?i)(https?://[^\s:/@]+:)[^\s/@]+(@)"), r"\1<REDACTED>\2"),
)


def redact_text(text: str, *, max_chars: int = 2048) -> str:
    """Platform-wide text safety policy for persisted or user-visible diagnostics."""

    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    out = str(text)
    for pattern, replacement in _PATTERNS:
        out = pattern.sub(replacement, out)
    out = " ".join(out.split())
    if len(out) > max_chars:
        out = out[: max_chars - 1] + "…"
    return out


def redact_value(value: object) -> object:
    if isinstance(value, Mapping):
        result: dict[object, object] = {}
        for key, item in value.items():
            result[key] = "<REDACTED>" if str(key).lower() in _SENSITIVE_KEYS else redact_value(item)
        return result
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


__all__ = ["redact_text", "redact_value"]
