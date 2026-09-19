from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, Protocol, TypeVar, runtime_checkable

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RegistrationKey:
    namespace: str
    name: str
    def __post_init__(self) -> None:
        if not self.namespace.strip() or not self.name.strip():
            raise ValueError("registration key fields must be non-empty")


class CapabilityLifetime(StrEnum):
    EXECUTION_SCOPE = "execution_scope"
    PARTICIPANT_SESSION = "participant_session"
    ENVIRONMENT_SESSION = "environment_session"


@dataclass(frozen=True, slots=True)
class CapabilityRegistration(Generic[T]):
    key: RegistrationKey
    value_type: type[T]
    owner_id: str
    lifetime: CapabilityLifetime = CapabilityLifetime.EXECUTION_SCOPE
    def __post_init__(self) -> None:
        if not self.owner_id.strip():
            raise ValueError("capability owner_id required")
        if not isinstance(self.value_type, type):
            raise TypeError("capability value_type must be a concrete runtime type")


class ScopeDisposed(RuntimeError): pass
class RegistrationConflict(RuntimeError): pass
class CapabilityTypeMismatch(TypeError): pass


@runtime_checkable
class RegistrationHandlePort(Protocol):
    @property
    def key(self) -> RegistrationKey: ...
    def close(self, *, timeout_s: float | None = None) -> None: ...


@runtime_checkable
class RegistrationLeasePort(Protocol, Generic[T]):
    @property
    def value(self) -> T: ...
    def close(self) -> None: ...


@runtime_checkable
class RegistrationScopePort(Protocol):
    @property
    def scope_id(self) -> str: ...
    def child(self, scope_id: str) -> "RegistrationScopePort": ...
    def register_typed(self, contract: CapabilityRegistration[T], value: T) -> RegistrationHandlePort: ...
    def acquire_typed(self, contract: CapabilityRegistration[T]) -> AbstractContextManager[T]: ...
    def dispose(self, *, timeout_s: float | None = None) -> None: ...


@runtime_checkable
class RegistrationScopeFactoryPort(Protocol):
    def create(self, scope_id: str) -> RegistrationScopePort: ...


__all__ = ["CapabilityLifetime", "CapabilityRegistration", "CapabilityTypeMismatch", "RegistrationConflict",
           "RegistrationHandlePort", "RegistrationKey", "RegistrationLeasePort", "RegistrationScopeFactoryPort",
           "RegistrationScopePort", "ScopeDisposed"]
