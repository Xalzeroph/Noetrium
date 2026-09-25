from __future__ import annotations

from noetrium_platform.capabilities.participant.definition.api import (
    ParticipantImplementationCatalogPort,
    ParticipantImplementationFactory,
    ParticipantImplementationIdentity,
    RegisteredParticipantImplementation,
)


class ParticipantImplementationCatalog(ParticipantImplementationCatalogPort):
    """Definition authority for implementation identities and factories."""

    def __init__(self) -> None:
        self._implementations: dict[str, RegisteredParticipantImplementation] = {}

    def register(
        self,
        identity: ParticipantImplementationIdentity,
        factory: ParticipantImplementationFactory,
    ) -> None:
        key = identity.digest()
        if key in self._implementations:
            raise ValueError(
                "duplicate participant implementation: "
                f"{identity.kind}:{identity.participant_id}:{identity.implementation_version}"
            )
        self._implementations[key] = RegisteredParticipantImplementation(identity, factory)

    def resolve(self, identity: ParticipantImplementationIdentity) -> RegisteredParticipantImplementation:
        try:
            registered = self._implementations[identity.digest()]
        except KeyError as exc:
            raise KeyError(
                "unknown participant implementation: "
                f"{identity.kind}:{identity.participant_id}:{identity.implementation_version}"
            ) from exc
        if registered.identity != identity:
            raise ValueError("participant implementation catalog identity collision")
        return registered

    def identities(self) -> tuple[ParticipantImplementationIdentity, ...]:
        return tuple(
            sorted(
                (row.identity for row in self._implementations.values()),
                key=lambda row: row.digest(),
            )
        )


__all__ = [
    "ParticipantImplementationCatalog",
    "ParticipantImplementationFactory",
    "RegisteredParticipantImplementation",
]
