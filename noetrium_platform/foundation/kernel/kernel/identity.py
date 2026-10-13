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








__all__ = [
    "ComponentIdentity",
    "ImmutableModelIdentity",
    "SystemIdentity",
]
