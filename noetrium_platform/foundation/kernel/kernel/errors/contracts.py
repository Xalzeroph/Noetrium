from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SafeExceptionDescriptor:
    error_type: str
    qualified_type: str
    safe_message: str
    error_digest: str


__all__ = ["SafeExceptionDescriptor"]
