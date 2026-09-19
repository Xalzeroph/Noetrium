from __future__ import annotations

"""Small, domain-neutral contracts for durable object boundaries."""

from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Protocol, TypeVar

from noetrium_platform.foundation.kernel.kernel import canonical_digest


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class DurableObjectIdentity:
    """Stable identity shared by a durable object and its publication receipt."""

    object_type: str
    object_id: str
    schema: str

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.object_type, self.object_id, self.schema)):
            raise ValueError("durable object identity fields must be non-empty")

    @property
    def digest(self) -> str:
        return canonical_digest({
            "object_type": self.object_type,
            "object_id": self.object_id,
            "schema": self.schema,
        })


@dataclass(frozen=True, slots=True)
class DurableWriteReceipt:
    identity: DurableObjectIdentity
    revision: int
    content_digest: str

    def __post_init__(self) -> None:
        if self.revision < 0 or len(self.content_digest) != 64:
            raise ValueError("durable write receipt is invalid")


class DurableObjectStorePort(Protocol, Generic[T]):
    """Minimal store contract; concurrency and corruption remain explicit errors."""

    def exists(self) -> bool: ...
    def read(self) -> T: ...
    def write(self, value: T) -> DurableWriteReceipt | None: ...


class DurableObjectStoreFactoryPort(Protocol, Generic[T]):
    def __call__(self, path: Path) -> DurableObjectStorePort[T]: ...


__all__ = [
    "DurableObjectIdentity",
    "DurableObjectStoreFactoryPort",
    "DurableObjectStorePort",
    "DurableWriteReceipt",
]
