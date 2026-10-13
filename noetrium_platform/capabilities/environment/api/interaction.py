from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from .contracts import Observation

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    JsonInput,
    JsonObject,
    JsonValue,
    canonical_digest,
    freeze_json,
    thaw_json,
)

class EnvironmentQueryKind(StrEnum):
    STATE = "state"
    CAPABILITIES = "capabilities"
    ENTITY = "entity"
    TASK = "task"
    ARTIFACT = "artifact"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class EnvironmentCapabilityDescriptor:
    capability_id: str
    version: str
    action_types: tuple[str, ...] = ()
    query_types: tuple[str, ...] = ()
    metadata: dict[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.capability_id.strip() or not self.version.strip():
            raise ValueError("environment capability identity is required")
        if any(not value.strip() for value in self.action_types + self.query_types):
            raise ValueError("environment capability names must be non-empty")
        object.__setattr__(self, "metadata", dict(thaw_json(freeze_json(self.metadata))))


@dataclass(frozen=True, slots=True)
class EnvironmentQuery:
    query_id: str
    query_type: str
    payload: JsonInput
    context: ExecutionContext

    def __post_init__(self) -> None:
        if not self.query_id.strip() or not self.query_type.strip():
            raise ValueError("environment query identity is required")
        object.__setattr__(self, "payload", freeze_json(self.payload))


@dataclass(frozen=True, slots=True)
class EnvironmentQueryResult:
    query_id: str
    supported: bool
    payload: JsonObject
    observation: Observation | None
    diagnostics: dict[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.query_id.strip():
            raise ValueError("environment query result query_id is required")
        if not isinstance(self.supported, bool):
            raise TypeError("environment query result supported must be boolean")
        object.__setattr__(self, "payload", dict(thaw_json(freeze_json(self.payload))))
        object.__setattr__(self, "diagnostics", dict(thaw_json(freeze_json(self.diagnostics))))



@runtime_checkable
class EnvironmentQueryPort(Protocol):
    def query(self, request: EnvironmentQuery) -> EnvironmentQueryResult: ...


@runtime_checkable
class EnvironmentCapabilityPort(Protocol):
    def capability_descriptors(self) -> tuple[EnvironmentCapabilityDescriptor, ...]: ...


@dataclass(frozen=True, slots=True)
class EnvironmentCoordinationRequest:
    coordination_id: str
    operation: str
    payload: JsonInput
    context: ExecutionContext

    def __post_init__(self) -> None:
        if not self.coordination_id.strip() or not self.operation.strip():
            raise ValueError("environment coordination identity is required")
        object.__setattr__(self, "payload", freeze_json(self.payload))


@dataclass(frozen=True, slots=True)
class EnvironmentCoordinationReceipt:
    coordination_id: str
    accepted: bool
    evidence_refs: tuple[str, ...] = ()
    diagnostics: dict[str, JsonValue] = field(default_factory=dict)


@runtime_checkable
class EnvironmentCoordinationPort(Protocol):
    def coordinate(self, request: EnvironmentCoordinationRequest) -> EnvironmentCoordinationReceipt: ...


__all__ = [
    "EnvironmentCapabilityDescriptor",
    "EnvironmentCoordinationPort",
    "EnvironmentCoordinationReceipt",
    "EnvironmentCoordinationRequest",
    "EnvironmentQuery",
    "EnvironmentQueryKind",
    "EnvironmentQueryPort",
    "EnvironmentQueryResult",
]
