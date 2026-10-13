from __future__ import annotations

class RuntimeLifecycleError(RuntimeError):
    """Base error for exact runtime lifecycle invariants."""


class FrozenRuntimeIdentityViolation(ValueError, RuntimeLifecycleError):
    """A frozen runtime identity no longer matches the observed/runtime binding."""


class RuntimeOperationalHealthUnavailable(RuntimeLifecycleError):
    """Required operational health evidence is unavailable or stale."""


__all__ = [
    "FrozenRuntimeIdentityViolation",
    "RuntimeLifecycleError",
    "RuntimeOperationalHealthUnavailable",
]
