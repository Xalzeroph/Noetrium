from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from .provider import (
    EnvironmentCapability,
    EnvironmentDiagnosticsPort,
    EnvironmentProviderCapabilities,
    EnvironmentProviderPort,
    EnvironmentSessionDiagnostics,
    EnvironmentSessionServices,
)
from .errors import EnvironmentCapabilityUnsupported
from .contracts import (
    ActionRequest,
    ActionResult,
    EnvironmentIdentity,
    EnvironmentSession,
    Observation,
)
from .branch_state import EnvironmentBranchStatePort
from .recovery import EnvironmentRecoverySession
from .reset import EnvironmentResetPort
from noetrium_platform.foundation.kernel.kernel import EffectReceipt, ExecutionContext, canonical_digest


@dataclass(frozen=True, slots=True)
class EnvironmentConformanceProbe:
    session_id: str
    context: ExecutionContext
    action: ActionRequest | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id.strip():
            raise ValueError("environment conformance session_id must be non-empty")
        if not isinstance(self.context, ExecutionContext):
            raise TypeError("environment conformance requires ExecutionContext")
        if self.action is not None and self.action.context != self.context:
            raise ValueError("environment conformance action context must match the probe context")


@dataclass(frozen=True, slots=True)
class EnvironmentProviderConformanceReceipt:
    environment: EnvironmentIdentity
    capabilities: EnvironmentProviderCapabilities
    session_id: str
    observation_id: str
    observation_generation: str
    checks: tuple[str, ...]
    snapshot_sha256: str | None = None
    action_id: str | None = None
    diagnostics_generation: str | None = None

    def digest(self) -> str:
        return canonical_digest(self)


def require_environment_provider_identity(identity: EnvironmentIdentity) -> None:
    fields = (
        identity.environment_id,
        identity.implementation_version,
        identity.abi_version,
        identity.schema_version,
    )
    if any(not isinstance(value, str) or not value.strip() for value in fields):
        raise ValueError("environment provider identity is incomplete")
    digest = identity.artifact_digest
    if (
        not isinstance(digest, str)
        or digest != digest.lower()
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        raise ValueError("environment provider artifact_digest must be canonical SHA-256")




__all__ = [
    "EnvironmentConformanceProbe",
    "EnvironmentProviderConformanceReceipt",
    "require_environment_provider_identity",
]
