from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ComponentIdentity:
    component_id: str
    implementation_id: str
    implementation_version: str
    schema_version: str
    generation_id: str


@dataclass(frozen=True, slots=True)
class ImmutableModelIdentity:
    logical_name: str
    model_id: str
    revision: str
    engine: str
    engine_version: str
    dtype: str
    quantization: str | None
    context_length: int
    tokenizer_revision: str | None = None

    def resume_key(self) -> tuple[object, ...]:
        return (
            self.model_id,
            self.revision,
            self.engine,
            self.engine_version,
            self.dtype,
            self.quantization,
            self.context_length,
            self.tokenizer_revision,
        )


@dataclass(frozen=True, slots=True)
class SystemIdentity:
    id: str
    version: str = "1"

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("system id must be non-empty")
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("system version must be non-empty")


@dataclass(frozen=True, slots=True)
class SystemSpec:
    identity: SystemIdentity
    purpose: str
    children: tuple[str, ...] = ()
    authorities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.identity, SystemIdentity):
            raise TypeError("system spec identity must be SystemIdentity")
        if not isinstance(self.purpose, str) or not self.purpose.strip():
            raise ValueError("system purpose must be non-empty")
        if not isinstance(self.children, tuple) or any(
            not isinstance(child, str) or not child.strip() for child in self.children
        ):
            raise TypeError("system children must be non-empty text values")
        if not isinstance(self.authorities, tuple) or any(
            not isinstance(authority, str) or not authority.strip()
            for authority in self.authorities
        ):
            raise TypeError("system authorities must be non-empty text values")


@runtime_checkable
class SystemPort(Protocol):
    @property
    def spec(self) -> SystemSpec: ...


class SystemService(SystemPort):
    """Shared framework-only system boundary; behavior belongs to child providers."""

    def __init__(self, spec: SystemSpec) -> None:
        self._spec = spec

    @property
    def spec(self) -> SystemSpec:
        return self._spec


__all__ = [
    "ComponentIdentity",
    "ImmutableModelIdentity",
    "SystemIdentity",
    "SystemPort",
    "SystemService",
    "SystemSpec",
]
