from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from collections.abc import Mapping
from typing import Generic, Protocol, TypeAlias, TypeVar, runtime_checkable

from noetrium_platform.evidence.data.record.api import ExecutionRecordPlane

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]
JsonObject: TypeAlias = Mapping[str, JsonValue]


TDecoded_co = TypeVar("TDecoded_co", covariant=True)


@dataclass(frozen=True, slots=True)
class FactSchema(Generic[TDecoded_co]):
    fact_type: str
    schema_version: str

    def __post_init__(self) -> None:
        if not self.fact_type.strip() or not self.schema_version.strip():
            raise ValueError("fact schema identity fields must be non-empty")


class FactCriticality(StrEnum):
    REQUIRED = "required"
    IGNORABLE = "ignorable"


@dataclass(frozen=True, slots=True)
class DurableFact:
    fact_id: str
    fact_type: str
    schema_version: str
    criticality: FactCriticality
    payload: JsonObject
    artifact_refs: tuple[str, ...] = ()
    state_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate every artifact/state reference before accepting durable fact authority.

        Algorithm-Complexity: O(N)
        Algorithm-Rationale: N is the total durable reference cardinality; every reference must be checked for non-empty identity and uniqueness.
        """
        if not self.fact_id.strip() or not self.fact_type.strip() or not self.schema_version.strip():
            raise ValueError("durable fact identity fields must be non-empty")
        for name, refs in (("artifact_refs", self.artifact_refs), ("state_refs", self.state_refs)):
            if any(not ref.strip() for ref in refs):
                raise ValueError(f"durable fact {name} must contain only non-empty references")
            if len(set(refs)) != len(refs):
                raise ValueError(f"durable fact {name} must be unique")

    @property
    def record_plane(self) -> ExecutionRecordPlane:
        return ExecutionRecordPlane.DURABLE_FACT


@dataclass(frozen=True, slots=True)
class DurableFactReceipt:
    fact_id: str
    sequence: int
    record_sha256: str

    def __post_init__(self) -> None:
        if not self.fact_id.strip() or self.sequence <= 0:
            raise ValueError("durable fact receipt identity/sequence must be valid")
        if len(self.record_sha256) != 64 or any(char not in "0123456789abcdef" for char in self.record_sha256):
            raise ValueError("durable fact receipt record_sha256 must be lowercase SHA-256")


class UnknownRequiredFact(RuntimeError):
    pass


class DurableFactConflict(RuntimeError):
    pass


class DurableFactCorruptionError(RuntimeError):
    pass


class DurableFactNotFound(KeyError):
    pass


@runtime_checkable
class DurableFactSinkPort(Protocol):
    def append(self, fact: DurableFact) -> DurableFactReceipt: ...


@runtime_checkable
class DurableFactStorePort(DurableFactSinkPort, Protocol):
    def get(self, fact_id: str) -> DurableFact: ...
    def count(self) -> int: ...


@runtime_checkable
class FactDecoderPort(Protocol[TDecoded_co]):
    schema: FactSchema[TDecoded_co]

    def decode(self, fact: DurableFact) -> TDecoded_co: ...


__all__ = [
    "DurableFact",
    "DurableFactConflict",
    "DurableFactCorruptionError",
    "DurableFactNotFound",
    "DurableFactReceipt",
    "DurableFactSinkPort",
    "DurableFactStorePort",
    "FactCriticality",
    "FactDecoderPort",
    "FactSchema",
    "UnknownRequiredFact",
]
