from __future__ import annotations


class ServerReleaseLayoutError(RuntimeError):
    """The requested immutable release directory is absent or unsafe."""


class ServerSessionPolicyMismatch(RuntimeError):
    """The session transport or frozen run policy does not match."""


class ServerRuntimeLaunchManifestMismatch(RuntimeError):
    """The controller command differs from the frozen launch manifest."""


__all__ = [
    "ServerReleaseLayoutError",
    "ServerRuntimeLaunchManifestMismatch",
    "ServerSessionPolicyMismatch",
]
