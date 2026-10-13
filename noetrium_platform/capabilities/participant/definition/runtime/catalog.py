from __future__ import annotations

from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.capabilities.participant.core.api import (
    participant_implementation_digest,
    participant_implementation_id,
    participant_implementation_kind,
    participant_implementation_version,
    require_participant_implementation,
)

from noetrium_platform.capabilities.participant.definition.api import (
    ParticipantImplementationCatalogPort,
    ParticipantImplementationFactory,
    RegisteredParticipantImplementation,
)


class ParticipantImplementationCatalog(ParticipantImplementationCatalogPort):
    """Definition authority for implementation identities and factories."""

    def __init__(self) -> None:
        self._implementations: dict[str, RegisteredParticipantImplementation] = {}

    def register(
        self,
        identity: NoetriumUnit,
        factory: ParticipantImplementationFactory,
    ) -> None:
        identity = require_participant_implementation(identity)
        key = participant_implementation_digest(identity)
        if key in self._implementations:
            raise ValueError(
                "duplicate participant implementation: "
                f"{participant_implementation_kind(identity)}:{participant_implementation_id(identity)}:{participant_implementation_version(identity)}"
            )
        self._implementations[key] = RegisteredParticipantImplementation(identity, factory)

    def resolve(self, identity: NoetriumUnit) -> RegisteredParticipantImplementation:
        try:
            registered = self._implementations[participant_implementation_digest(identity)]
        except KeyError as exc:
            raise KeyError(
                "unknown participant implementation: "
                f"{participant_implementation_kind(identity)}:{participant_implementation_id(identity)}:{participant_implementation_version(identity)}"
            ) from exc
        if registered.identity != identity:
            raise ValueError("participant implementation catalog identity collision")
        return registered

    def identities(self) -> tuple[NoetriumUnit, ...]:
        return tuple(
            sorted(
                (row.identity for row in self._implementations.values()),
                key=participant_implementation_digest,
            )
        )


__all__ = [
    "ParticipantImplementationCatalog",
    "ParticipantImplementationFactory",
    "RegisteredParticipantImplementation",
]
