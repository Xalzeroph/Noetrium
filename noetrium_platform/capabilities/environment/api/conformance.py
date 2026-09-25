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


def _require_provider_identity(identity: EnvironmentIdentity) -> None:
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


def verify_environment_provider_conformance(
    provider: EnvironmentProviderPort,
    *,
    probe: EnvironmentConformanceProbe,
    services: EnvironmentSessionServices,
) -> EnvironmentProviderConformanceReceipt:
    """Exercise only the public provider/session seam and fail closed on identity drift."""

    if not isinstance(provider, EnvironmentProviderPort):
        raise TypeError("provider does not satisfy EnvironmentProviderPort")
    identity = provider.identity
    if not isinstance(identity, EnvironmentIdentity):
        raise TypeError("environment provider exposes the wrong identity type")
    _require_provider_identity(identity)
    capabilities = provider.capabilities
    if not isinstance(capabilities, EnvironmentProviderCapabilities):
        raise TypeError("environment provider exposes untyped capabilities")

    session = provider.open_session(session_id=probe.session_id, services=services)
    if not isinstance(session, EnvironmentSession):
        raise TypeError("provider returned a session outside EnvironmentSession")

    checks: list[str] = ["provider_identity", "open_session"]
    snapshot_digest: str | None = None
    action_id: str | None = None
    diagnostics_generation: str | None = None
    try:
        observation = session.observe(probe.context)
        if not isinstance(observation, Observation):
            raise TypeError("environment session observe() returned the wrong type")
        if not observation.observation_id.strip() or not observation.generation.strip():
            raise ValueError("environment observation identity is incomplete")
        checks.append("observe")

        if capabilities.supports(EnvironmentCapability.BRANCH_STATE):
            if not isinstance(session, EnvironmentBranchStatePort):
                raise TypeError("branch-state capability lacks EnvironmentBranchStatePort")
            checks.append("branch_state_port")

        if capabilities.supports(EnvironmentCapability.RESET):
            if not isinstance(session, EnvironmentResetPort):
                raise TypeError("reset capability lacks EnvironmentResetPort")
            observation = session.reset(probe.context)
            if not isinstance(observation, Observation):
                raise TypeError("environment reset returned the wrong type")
            if not observation.observation_id.strip() or not observation.generation.strip():
                raise ValueError("environment reset observation identity is incomplete")
            checks.append("reset")

        payload: bytes | None = None
        if capabilities.supports(EnvironmentCapability.SNAPSHOT):
            if not isinstance(session, EnvironmentRecoverySession):
                raise TypeError("snapshot capability lacks EnvironmentRecoverySession")
            payload = session.checkpoint()
            if not isinstance(payload, bytes) or not payload:
                raise TypeError("environment snapshot must be non-empty bytes")
            snapshot_digest = sha256(payload).hexdigest()
            checks.append("snapshot")
        else:
            try:
                session.checkpoint()
            except EnvironmentCapabilityUnsupported as exc:
                if exc.capability != EnvironmentCapability.SNAPSHOT.value:
                    raise ValueError("snapshot unsupported capability identity drift") from exc
            else:
                raise ValueError("snapshot behavior contradicts provider capabilities")
            checks.append("snapshot_unsupported")

        if capabilities.supports(EnvironmentCapability.RESTORE):
            if not isinstance(session, EnvironmentRecoverySession):
                raise TypeError("restore capability lacks EnvironmentRecoverySession")
            if payload is None:
                raise ValueError("restore capability requires an available snapshot")
            session.restore(payload)
            checks.append("restore")
        else:
            try:
                session.restore(payload or b"")
            except EnvironmentCapabilityUnsupported as exc:
                if exc.capability != EnvironmentCapability.RESTORE.value:
                    raise ValueError("restore unsupported capability identity drift") from exc
            else:
                raise ValueError("restore behavior contradicts provider capabilities")
            checks.append("restore_unsupported")

        if probe.action is not None:
            result = session.act(probe.action)
            if not isinstance(result, ActionResult) or result.action_id != probe.action.action_id:
                raise TypeError("environment session returned an invalid action result")
            action_id = result.action_id
            checks.append("act")
            if capabilities.supports(EnvironmentCapability.RECONCILE):
                if not isinstance(result.effect, EffectReceipt):
                    raise TypeError("reconcilable environment action must return EffectReceipt")
                reconciled = session.reconcile(result.effect, probe.context)
                if not isinstance(reconciled, EffectReceipt):
                    raise TypeError("environment reconcile() returned the wrong type")
                if reconciled.request_digest != result.effect.request_digest:
                    raise ValueError("environment reconciliation changed request identity")
                checks.append("reconcile")
            elif isinstance(result.effect, EffectReceipt):
                try:
                    session.reconcile(result.effect, probe.context)
                except EnvironmentCapabilityUnsupported as exc:
                    if exc.capability != EnvironmentCapability.RECONCILE.value:
                        raise ValueError("reconcile unsupported capability identity drift") from exc
                else:
                    raise ValueError("reconcile behavior contradicts provider capabilities")
                checks.append("reconcile_unsupported")

        if capabilities.supports(EnvironmentCapability.DIAGNOSTICS):
            if not isinstance(session, EnvironmentDiagnosticsPort):
                raise TypeError("diagnostics capability lacks EnvironmentDiagnosticsPort")
            diagnostics = session.diagnostics_snapshot()
            if not isinstance(diagnostics, EnvironmentSessionDiagnostics):
                raise TypeError("environment diagnostics returned the wrong type")
            if diagnostics.session_id != probe.session_id or diagnostics.environment != identity:
                raise ValueError("environment diagnostics identity drift")
            if diagnostics.generation != observation.generation:
                raise ValueError("environment diagnostics generation drift")
            if diagnostics.closed or not diagnostics.ready:
                raise ValueError("newly opened environment session is not ready")
            diagnostics_generation = diagnostics.generation
            checks.append("diagnostics")
    finally:
        session.close()

    return EnvironmentProviderConformanceReceipt(
        environment=identity,
        capabilities=capabilities,
        session_id=probe.session_id,
        observation_id=observation.observation_id,
        observation_generation=observation.generation,
        checks=tuple(checks),
        snapshot_sha256=snapshot_digest,
        action_id=action_id,
        diagnostics_generation=diagnostics_generation,
    )


__all__ = [
    "EnvironmentConformanceProbe",
    "EnvironmentProviderConformanceReceipt",
    "verify_environment_provider_conformance",
]
