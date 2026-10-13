from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from .unit_semantics import require_participant_implementation


def _digest(value: object) -> str:
    return canonical_digest(value)


@lru_cache(maxsize=256)
def _participant_session_runtime_digest(
    runtime_id: str, runtime_version: str, abi_version: str, artifact_digest: str
) -> str:
    return _digest((runtime_id, runtime_version, abi_version, artifact_digest))


@lru_cache(maxsize=8192)
def _participant_runtime_binding_digest(
    role: str,
    implementation_digest: str,
    runtime_digest: str,
    configuration_digest: str | None,
) -> str:
    return _digest((role, implementation_digest, runtime_digest, configuration_digest))


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
        return _participant_session_runtime_digest(
            self.runtime_id, self.runtime_version, self.abi_version, self.artifact_digest
        )


@dataclass(frozen=True, slots=True, order=True)
class ParticipantRuntimeBinding:
    """Role-bound selection of implementation, session runtime and immutable configuration."""

    role: str
    implementation: NoetriumUnit
    runtime: ParticipantSessionRuntimeIdentity
    configuration_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.role.strip():
            raise ValueError("participant runtime role must be non-empty")
        require_participant_implementation(self.implementation)

    def digest(self) -> str:
        return _participant_runtime_binding_digest(
            self.role,
            self.implementation.unit_digest,
            self.runtime.digest(),
            self.configuration_digest,
        )


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
    "ParticipantRuntimeBinding",
    "ParticipantSessionRuntimeIdentity",
]
