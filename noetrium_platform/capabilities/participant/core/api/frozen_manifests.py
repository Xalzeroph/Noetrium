from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest

from .contracts import (
    ParticipantImplementationIdentity,
    ParticipantRuntimeBinding,
    ParticipantSessionRuntimeIdentity,
)


@dataclass(frozen=True, slots=True)
class ParticipantImplementationInventory:
    """Immutable scientific implementation evidence independent of runtime engines and run roles."""

    implementations: tuple[ParticipantImplementationIdentity, ...]
    schema_version: str = "participant-implementation-inventory.v2"

    def __post_init__(self) -> None:
        digests = [row.digest() for row in self.implementations]
        if len(digests) != len(set(digests)):
            raise ValueError("duplicate participant implementation in inventory")
        missing = tuple(
            f"{row.kind}:{row.participant_id}"
            for row in self.implementations
            if not row.artifact_digest or not row.artifact_digest.strip()
        )
        if missing:
            raise ValueError(
                "implementation inventory requires immutable artifact digests: " + ", ".join(missing)
            )

    @classmethod
    def from_bindings(cls, bindings: tuple[ParticipantRuntimeBinding, ...]) -> "ParticipantImplementationInventory":
        return cls(tuple(sorted({row.implementation for row in bindings}, key=lambda row: row.digest())))

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ParticipantRuntimeInventory:
    """Immutable session-runtime evidence independent of scientific implementations and roles."""

    runtimes: tuple[ParticipantSessionRuntimeIdentity, ...]
    schema_version: str = "participant-runtime-inventory.v1"

    def __post_init__(self) -> None:
        digests = [row.digest() for row in self.runtimes]
        if len(digests) != len(set(digests)):
            raise ValueError("duplicate participant session runtime in inventory")

    @classmethod
    def from_bindings(cls, bindings: tuple[ParticipantRuntimeBinding, ...]) -> "ParticipantRuntimeInventory":
        return cls(tuple(sorted({row.runtime for row in bindings}, key=lambda row: row.digest())))

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class ParticipantRuntimeBindingManifest:
    """Run-planning evidence binding roles to implementation + runtime + configuration."""

    implementation_inventory_digest: str
    runtime_inventory_digest: str
    bindings: tuple[ParticipantRuntimeBinding, ...]
    schema_version: str = "participant-runtime-binding-manifest.v2"

    def __post_init__(self) -> None:
        if not self.implementation_inventory_digest.strip() or not self.runtime_inventory_digest.strip():
            raise ValueError("runtime binding manifest requires implementation and runtime inventory digests")
        roles = [row.role for row in self.bindings]
        if len(roles) != len(set(roles)):
            raise ValueError("duplicate participant role in runtime binding manifest")

    @classmethod
    def build(
        cls,
        bindings: tuple[ParticipantRuntimeBinding, ...],
        implementation_inventory: ParticipantImplementationInventory,
        runtime_inventory: ParticipantRuntimeInventory,
    ) -> "ParticipantRuntimeBindingManifest":
        known_implementations = {row.digest() for row in implementation_inventory.implementations}
        missing_implementations = tuple(
            row.role for row in bindings if row.implementation.digest() not in known_implementations
        )
        if missing_implementations:
            raise ValueError(
                "runtime binding references implementation outside frozen inventory: "
                + ", ".join(missing_implementations)
            )
        known_runtimes = {row.digest() for row in runtime_inventory.runtimes}
        missing_runtimes = tuple(row.role for row in bindings if row.runtime.digest() not in known_runtimes)
        if missing_runtimes:
            raise ValueError(
                "runtime binding references session runtime outside frozen inventory: "
                + ", ".join(missing_runtimes)
            )
        return cls(
            implementation_inventory.digest(),
            runtime_inventory.digest(),
            tuple(sorted(bindings, key=lambda row: row.role)),
        )

    def digest(self) -> str:
        return canonical_digest(self)


__all__ = [
    "ParticipantImplementationInventory",
    "ParticipantRuntimeBindingManifest",
    "ParticipantRuntimeInventory",
]
