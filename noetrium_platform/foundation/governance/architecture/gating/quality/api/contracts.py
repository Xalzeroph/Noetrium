from __future__ import annotations

from dataclasses import dataclass


BANNED_RUNTIME_IDENTIFIERS = frozenset({
    "fallback_model", "fallback_models", "model_fallback",
    "fallback_prompt", "prompt_fallback", "truncate_prompt", "truncate_context",
    "reduce_context", "context_fallback", "lower_precision", "downgrade_precision",
    "fallback_method", "method_fallback", "sequential_fallback", "fallback_environment",
    "environment_fallback", "fallback_tool", "tool_fallback",
})

FORBIDDEN_ENABLED_CONFIG_KEYS = frozenset({
    "allow_model_fallback", "allow_precision_downgrade", "allow_context_downgrade",
    "allow_prompt_truncation", "allow_prompt_fallback", "allow_method_fallback",
    "allow_environment_fallback", "allow_tool_fallback", "allow_quality_downgrade",
    "allow_sequential_fallback",
})

FORBIDDEN_NONEMPTY_CONFIG_KEYS = frozenset({
    "fallback_model", "fallback_models", "fallback_prompt", "fallback_prompts",
    "fallback_method", "fallback_methods", "fallback_environment", "fallback_environments",
    "fallback_tool", "fallback_tools", "fallback_precision", "fallback_context",
})


@dataclass(frozen=True, slots=True)
class DegradationFinding:
    path: str
    line: int
    identifier: str
    kind: str


@dataclass(frozen=True, slots=True)
class SilentFailureFinding:
    path: str
    line: int
    kind: str
    detail: str


__all__ = [
    "BANNED_RUNTIME_IDENTIFIERS", "DegradationFinding",
    "FORBIDDEN_ENABLED_CONFIG_KEYS", "FORBIDDEN_NONEMPTY_CONFIG_KEYS",
    "SilentFailureFinding",
]
