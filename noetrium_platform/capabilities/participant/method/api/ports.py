from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.capabilities.participant.core.api import (
    participant_implementation_digest,
    participant_implementation_kind,
    require_participant_implementation,
)

from .contracts import MethodSession
from .observability import MethodObservationOutboxBuilder, MethodServices


@dataclass(frozen=True, slots=True)
class MethodRuntimeIdentity:
    """Identity of the session execution engine, independent of method behavior."""

    runtime_id: str
    runtime_version: str
    abi_version: str
    artifact_digest: str

    def __post_init__(self) -> None:
        if any(not value.strip() for value in (
            self.runtime_id, self.runtime_version, self.abi_version, self.artifact_digest
        )):
            raise ValueError("method runtime identity fields must be non-empty")
        require_sha256(self.artifact_digest, "method runtime artifact_digest")


@dataclass(frozen=True, slots=True)
class MethodRuntimeBinding:
    """Explicit pairing of one scientific implementation Unit and runtime identity."""

    implementation: NoetriumUnit
    runtime: MethodRuntimeIdentity

    def __post_init__(self) -> None:
        require_participant_implementation(self.implementation)
        if participant_implementation_kind(self.implementation) != "method":
            raise ValueError("MethodRuntimeBinding implementation kind must be method")

    def digest(self) -> str:
        return canonical_digest({
            "method_implementation_digest": participant_implementation_digest(self.implementation),
            "method_session_runtime": self.runtime,
        })

 

@runtime_checkable
class MethodImplementation(Protocol):
    """Scientific method implementation/configuration without lifecycle execution authority."""

    @property
    def identity(self) -> NoetriumUnit: ...


@runtime_checkable
class MethodSessionRuntime(Protocol):
    """Execution engine that opens sessions for a separately supplied implementation."""

    @property
    def runtime_identity(self) -> MethodRuntimeIdentity: ...

    def open_session(
        self,
        implementation: MethodImplementation,
        *,
        binding: MethodRuntimeBinding,
        session_id: str,
        services: MethodServices,
    ) -> MethodSession: ...


@runtime_checkable
class MethodEndpointPort(Protocol):
    """Project/method-facing bound implementation + runtime endpoint."""

    @property
    def identity(self) -> NoetriumUnit: ...

    @property
    def runtime_identity(self) -> MethodRuntimeIdentity: ...

    @property
    def binding(self) -> MethodRuntimeBinding: ...

    @property
    def binding_digest(self) -> str: ...

    def open_session(self, *, session_id: str, services: MethodServices) -> MethodSession: ...


MethodEndpointBinder = Callable[
    [MethodImplementation, MethodSessionRuntime],
    MethodEndpointPort,
]



@dataclass(frozen=True, slots=True)
class MethodCompositionPorts:
    """All generic Participant/Method services a concrete method may require to compose."""

    bind_endpoint: MethodEndpointBinder
    build_observation_outbox: MethodObservationOutboxBuilder


__all__ = [
    "MethodCompositionPorts",
    "MethodEndpointBinder",
    "MethodEndpointPort",
    "MethodImplementation",
    "MethodRuntimeBinding",
    "MethodRuntimeIdentity",
    "MethodSessionRuntime",
]
