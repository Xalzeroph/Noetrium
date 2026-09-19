from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.capabilities.participant.core.api.contracts import (
    ParticipantImplementationIdentity,
    ParticipantSessionRuntimeIdentity,
)
from noetrium_platform.capabilities.participant.session.runtime import LocalParticipantRuntimeEndpoint

from ..runtime import (
    MinecraftEnvironmentImplementation,
    MinecraftEnvironmentRuntime,
    MinecraftEnvironmentSession,
)
from ..api.ports import MinecraftSessionServices


@dataclass(frozen=True, slots=True)
class MinecraftParticipantRuntimeAdapter:
    """Composition-only adapter from MC runtime identity to participant ABI.

    The MC environment package remains independent of participant internals.
    Only this composition leaf imports the participant binding identity needed
    by the generic participant resolver.
    """

    runtime: MinecraftEnvironmentRuntime

    @property
    def runtime_identity(self) -> ParticipantSessionRuntimeIdentity:
        identity = self.runtime.runtime_identity
        return ParticipantSessionRuntimeIdentity(
            runtime_id=identity.runtime_id,
            runtime_version=identity.runtime_version,
            abi_version=identity.abi_version,
            artifact_digest=identity.artifact_digest,
        )

    def open_session(
        self,
        implementation: MinecraftEnvironmentImplementation,
        *,
        session_id: str,
        services: MinecraftSessionServices,
    ) -> MinecraftEnvironmentSession:
        return self.runtime.open_session(implementation, session_id=session_id, services=services)


def compose_minecraft_participant_endpoint(
    implementation: MinecraftEnvironmentImplementation,
    runtime: MinecraftEnvironmentRuntime,
) -> LocalParticipantRuntimeEndpoint:
    """Join MC implementation and runtime through the generic participant seam.

    This is intentionally a composition adapter: Minecraft owns its domain
    identity and session semantics, while participant runtime owns the generic
    endpoint shape. No second MC-specific lifecycle endpoint is introduced.
    """

    if not isinstance(implementation, MinecraftEnvironmentImplementation):
        raise TypeError(
            "Minecraft participant implementation must be "
            "MinecraftEnvironmentImplementation"
        )
    identity = implementation.identity
    implementation_identity = ParticipantImplementationIdentity(
        kind="environment",
        participant_id=identity.environment_id,
        implementation_version=identity.implementation_version,
        abi_version=identity.abi_version,
        schema_version=identity.schema_version,
        artifact_digest=identity.artifact_digest,
    )
    adapter = MinecraftParticipantRuntimeAdapter(runtime)
    return LocalParticipantRuntimeEndpoint(
        implementation_identity=implementation_identity,
        runtime_identity=adapter.runtime_identity,
        implementation=implementation,
        runtime=adapter,
    )


__all__ = ["MinecraftParticipantRuntimeAdapter", "compose_minecraft_participant_endpoint"]
