from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256


def _digest(value: object) -> str:
    return canonical_digest(value)


@dataclass(frozen=True, slots=True, order=True)
class ParticipantImplementationIdentity:
    """Identity of implementation code/ABI only; contains no run role or runtime configuration."""

    kind: str
    participant_id: str
    implementation_version: str
    abi_version: str
    schema_version: str
    artifact_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.kind.strip() or not self.participant_id.strip():
            raise ValueError("participant implementation kind/id must be non-empty")
        if not self.implementation_version.strip() or not self.abi_version.strip() or not self.schema_version.strip():
            raise ValueError("participant implementation version/ABI/schema must be non-empty")
        if self.artifact_digest is not None:
            require_sha256(self.artifact_digest, "participant implementation artifact_digest")

    def digest(self) -> str:
        return _digest((
            self.kind,
            self.participant_id,
            self.implementation_version,
            self.abi_version,
            self.schema_version,
            self.artifact_digest,
        ))




@dataclass(frozen=True, slots=True, order=True)
class ParticipantSessionRuntimeIdentity:
    """Identity of the participant session execution engine, separate from scientific implementation."""

    runtime_id: str
    runtime_version: str
    abi_version: str
    artifact_digest: str

    def __post_init__(self) -> None:
        if any(not value.strip() for value in (self.runtime_id, self.runtime_version, self.abi_version, self.artifact_digest)):
            raise ValueError("participant runtime identity fields must be non-empty")
        require_sha256(self.artifact_digest, "participant session runtime artifact_digest")

    def digest(self) -> str:
        return _digest((self.runtime_id, self.runtime_version, self.abi_version, self.artifact_digest))


@dataclass(frozen=True, slots=True, order=True)
class ParticipantRuntimeBinding:
    """Role-bound selection of implementation, session runtime and immutable configuration."""

    role: str
    implementation: ParticipantImplementationIdentity
    runtime: ParticipantSessionRuntimeIdentity
    configuration_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.role.strip():
            raise ValueError("participant runtime role must be non-empty")

    def digest(self) -> str:
        return _digest((self.role, self.implementation.digest(), self.runtime.digest(), self.configuration_digest))


@dataclass(frozen=True, slots=True)
class ParticipantConfigurationArtifact:
    """Opaque immutable runtime configuration. The implementation receives bytes, never RuntimeManager state."""

    configuration_digest: str | None
    opaque_payload: bytes
    schema_version: str = "1"

    @classmethod
    def empty(cls) -> "ParticipantConfigurationArtifact":
        return cls(None, b"", "1")


__all__ = [
    "ParticipantConfigurationArtifact",
    "ParticipantImplementationIdentity",
    "ParticipantRuntimeBinding",
    "ParticipantSessionRuntimeIdentity",
]
