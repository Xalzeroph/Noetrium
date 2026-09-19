from __future__ import annotations

from typing import Protocol

from noetrium_platform.foundation.kernel.kernel import ComponentIdentity
from noetrium_platform.capabilities.participant.core.api.checkpoint import ParticipantCheckpoint
from noetrium_platform.capabilities.participant.core.api.contracts import ParticipantImplementationIdentity, ParticipantRuntimeBinding
from noetrium_platform.capabilities.participant.core.api.runtime import ParticipantResolverPort, ParticipantRuntimeHandle
from noetrium_platform.capabilities.participant.core.api.lifecycle import ParticipantIdentityMismatch


class ParticipantDomainPolicy(Protocol):
    kind: str

    def implementation_identity(self, plugin: object) -> ParticipantImplementationIdentity: ...
    def open_session(self, plugin: object, *, session_id: str, services: object) -> object: ...
    def checkpoint(self, plugin: object, session: object, *, session_id: str) -> bytes: ...
    def restore(self, plugin: object, session: object, payload: bytes, *, session_id: str) -> None: ...


class PolicyParticipantAdapter:
    """Execution adapter over a resolver; it never sees implementation factories/config catalogs."""

    def __init__(self, resolver: ParticipantResolverPort, policy: ParticipantDomainPolicy) -> None:
        self._resolver = resolver
        self._policy = policy
        self.kind = policy.kind

    @staticmethod
    def _component(binding) -> ComponentIdentity:
        implementation = binding.implementation
        return ComponentIdentity(
            f"participant.{binding.role}",
            binding.digest(),
            implementation.implementation_version,
            implementation.schema_version,
            binding.runtime.digest(),
        )

    def resolve(self, binding: ParticipantRuntimeBinding) -> ParticipantRuntimeHandle:
        return self._resolver.resolve(binding)

    def frozen_component(self, binding: ParticipantRuntimeBinding) -> ComponentIdentity:
        return self._component(binding)

    def actual_component(self, participant: ParticipantRuntimeHandle) -> ComponentIdentity:
        return self._component(participant.binding)

    def validate(self, binding: ParticipantRuntimeBinding, participant: ParticipantRuntimeHandle) -> None:
        expected = binding
        if participant.binding != expected:
            raise ParticipantIdentityMismatch(
                f"participant runtime binding mismatch: expected={expected!r} actual={participant.binding!r}"
            )
        actual_implementation = self._policy.implementation_identity(participant.endpoint)
        if actual_implementation != expected.implementation:
            raise ParticipantIdentityMismatch(
                f"participant implementation mismatch: expected={expected.implementation!r} actual={actual_implementation!r}"
            )
        actual_runtime = getattr(participant.endpoint, "runtime_identity", None)
        if actual_runtime != expected.runtime:
            raise ParticipantIdentityMismatch(
                f"participant session runtime mismatch: expected={expected.runtime!r} actual={actual_runtime!r}"
            )

    def open_session(self, participant: ParticipantRuntimeHandle, *, session_id: str, services: object) -> object:
        return self._policy.open_session(participant.endpoint, session_id=session_id, services=services)

    @staticmethod
    def close_session(session: object) -> None:
        session.close()

    def checkpoint(
        self, participant: ParticipantRuntimeHandle, session: object, *, session_id: str
    ) -> ParticipantCheckpoint:
        payload = self._policy.checkpoint(participant.endpoint, session, session_id=session_id)
        if not isinstance(payload, bytes):
            raise TypeError("ParticipantDomainPolicy.checkpoint must return bytes")
        return ParticipantCheckpoint.capture(
            binding=participant.binding,
            component=self.actual_component(participant),
            session_id=session_id,
            opaque_payload=payload,
        )

    def restore(
        self, participant: ParticipantRuntimeHandle, session: object,
        checkpoint: ParticipantCheckpoint, *, session_id: str
    ) -> None:
        self._policy.restore(
            participant.endpoint, session, checkpoint.opaque_payload, session_id=session_id
        )


__all__ = ["ParticipantDomainPolicy", "PolicyParticipantAdapter"]
