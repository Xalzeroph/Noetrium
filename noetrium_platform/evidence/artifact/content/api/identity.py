from __future__ import annotations

from typing import Protocol, runtime_checkable

from noetrium_platform.evidence.artifact.api import ArtifactContentIdentity
from noetrium_platform.foundation.scope.api import ScopeIdentity


_HEX = frozenset("0123456789abcdef")


class ArtifactContentIdentityVerificationError(RuntimeError):
    """A claimed immutable content identity cannot be verified against Artifact authority."""

    def __init__(self, code: str, message: str) -> None:
        if type(code) is not str or not code.strip():
            raise ValueError("artifact content identity verification code must be non-empty")
        self.code = code
        super().__init__(f"artifact content identity verification failed [{code}]: {message}")


@runtime_checkable
class ArtifactContentIdentityResolverPort(Protocol):
    """Read-only Artifact authority for verified immutable content identities."""

    def verify(self, identity: ArtifactContentIdentity) -> ArtifactContentIdentity: ...

    def load(self, artifact_id: str) -> ArtifactContentIdentity: ...

    def snapshot_reference(
        self,
        reference_id: str,
        scope: ScopeIdentity,
    ) -> ArtifactContentIdentity: ...


__all__ = [
    "ArtifactContentIdentityResolverPort",
    "ArtifactContentIdentityVerificationError",
]
