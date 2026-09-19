"""Compatibility import path for governance/quality public contracts."""

from .api.contracts import (
    BANNED_RUNTIME_IDENTIFIERS,
    DegradationFinding,
    FORBIDDEN_ENABLED_CONFIG_KEYS,
    FORBIDDEN_NONEMPTY_CONFIG_KEYS,
)

__all__ = [
    "BANNED_RUNTIME_IDENTIFIERS", "DegradationFinding",
    "FORBIDDEN_ENABLED_CONFIG_KEYS", "FORBIDDEN_NONEMPTY_CONFIG_KEYS",
]
