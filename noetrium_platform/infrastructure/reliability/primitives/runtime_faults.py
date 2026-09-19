from __future__ import annotations


class RuntimeFault(RuntimeError):
    """Base class for runtime failures with platform-level recovery semantics."""


class FrozenRuntimeIdentityViolation(ValueError, RuntimeFault):
    """Frozen code/config/model/method/environment identity differs from the live binding.

    Restarting or reconciling a process must never be used to paper over this class of
    failure.  The operator must correct the deployment/manifest mismatch explicitly.
    """


class RuntimeOperationalHealthUnavailable(RuntimeFault):
    """The frozen identity is still valid, but a required live runtime is unavailable."""


__all__ = [
    "FrozenRuntimeIdentityViolation",
    "RuntimeFault",
    "RuntimeOperationalHealthUnavailable",
]
