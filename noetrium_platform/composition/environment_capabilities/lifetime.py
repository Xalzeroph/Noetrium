from __future__ import annotations

from typing import Protocol, runtime_checkable

from noetrium_platform.capabilities.environment.api import EnvironmentCapabilityDescriptor, EnvironmentSession
from noetrium_platform.capabilities.participant.capability.api import CapabilityDescriptor
from noetrium_platform.foundation.kernel.kernel import (
    EffectClass,
    ExecutionContext,
    canonical_digest,
    require_sha256,
)

from .action import EnvironmentSessionCapabilityAdapter, environment_capability_descriptor_metadata


@runtime_checkable
class EnvironmentLifetimeSessionAuthorityPort(Protocol):
    """Own exact EnvironmentSession lifecycle keyed by research lifetime identity."""

    @property
    def identity_digest(self) -> str: ...

    @property
    def effect_recovery_durability(self) -> str: ...

    def capability_descriptors(self) -> tuple[EnvironmentCapabilityDescriptor, ...]: ...

    def prepare(self, context: ExecutionContext) -> None: ...

    def session_for(self, context: ExecutionContext) -> EnvironmentSession: ...

    def release(self, lifetime_id: str) -> None: ...

    def close(self) -> None: ...


class LifetimeRoutedEnvironmentCapability:
    """Resolve the Environment provider session for each execution lifetime.

    This object owns only lifetime/session routing. Generic capability mediation
    and effect prepare/execute/reconcile remain exclusively owned by
    StudyCapabilityRouter + CapabilityEffectExecutor.
    """

    def __init__(
        self,
        sessions: EnvironmentLifetimeSessionAuthorityPort,
        *,
        capability_id: str = "environment.act",
    ) -> None:
        if not isinstance(sessions, EnvironmentLifetimeSessionAuthorityPort):
            raise TypeError(
                "lifetime-routed environment capability requires session authority"
            )
        if type(capability_id) is not str or not capability_id.strip():
            raise ValueError("lifetime-routed capability_id must be non-empty")
        require_sha256(
            sessions.identity_digest,
            "environment lifetime session authority identity",
        )
        self._sessions = sessions
        self._capability_id = capability_id.strip()
        self._descriptor = CapabilityDescriptor(
            capability_id=self._capability_id,
            interface_version="1",
            request_schema="noetrium.environment.action-capability.request.v1",
            result_schema="noetrium.environment.action-capability.result.v1",
            effect_class=EffectClass.RECONCILABLE,
            deterministic=False,
            metadata=environment_capability_descriptor_metadata(
                sessions.capability_descriptors()
            ),
        )
        self._identity_digest = canonical_digest(
            {
                "schema": "noetrium.lifetime-routed-environment-capability.v2",
                "session_authority_digest": sessions.identity_digest,
                "capability_id": self._capability_id,
            }
        )

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    @property
    def effect_recovery_durability(self) -> str:
        return self._sessions.effect_recovery_durability

    @property
    def capabilities(self) -> tuple[CapabilityDescriptor, ...]:
        return (self._descriptor,)

    def prepare(self, context: ExecutionContext) -> None:
        self._sessions.prepare(context)

    def session_for(self, context: ExecutionContext) -> EnvironmentSessionCapabilityAdapter:
        lifetime_id = context.lifetime_id
        if type(lifetime_id) is not str or not lifetime_id.strip():
            raise ValueError(
                "environment capability requires ExecutionContext.lifetime_id"
            )
        return EnvironmentSessionCapabilityAdapter(
            self._sessions.session_for(context),
            capability_id=self._capability_id,
        )

    def release(self, lifetime_id: str) -> None:
        self._sessions.release(lifetime_id)

    def close(self) -> None:
        self._sessions.close()


__all__ = [
    "EnvironmentLifetimeSessionAuthorityPort",
    "LifetimeRoutedEnvironmentCapability",
]
