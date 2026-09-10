"""Declarative registry for domain Machine families.

This registry describes execution capability, not the system topology.  The
governance catalog remains the sole owner of system identity and ownership.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Protocol, runtime_checkable

from .canonical import canonical_digest
from .machine import MachineKind


@dataclass(frozen=True, slots=True)
class MachineFamilyDescriptor:
    family_id: str
    kind: MachineKind
    implementation_version: str
    state_schema: str
    command_kinds: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    provided_capabilities: tuple[str, ...] = ()
    family_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for value in (
            self.family_id,
            self.implementation_version,
            self.state_schema,
        ):
            if type(value) is not str or not value.strip():
                raise ValueError("machine family identity fields are required")
        if not isinstance(self.kind, MachineKind):
            raise TypeError("machine family kind must be MachineKind")
        for name, values in (
            ("command_kinds", self.command_kinds),
            ("required_capabilities", self.required_capabilities),
            ("provided_capabilities", self.provided_capabilities),
        ):
            if type(values) is not tuple or any(
                type(value) is not str or not value.strip() for value in values
            ):
                raise TypeError(f"machine family {name} must be non-empty text tuple")
            if len(set(values)) != len(values):
                raise ValueError(f"machine family {name} must be unique")
        object.__setattr__(
            self,
            "family_digest",
            canonical_digest({
                "family_id": self.family_id,
                "kind": self.kind.value,
                "implementation_version": self.implementation_version,
                "state_schema": self.state_schema,
                "command_kinds": self.command_kinds,
                "required_capabilities": self.required_capabilities,
                "provided_capabilities": self.provided_capabilities,
            }),
        )


@runtime_checkable
class MachineFamilyRegistryPort(Protocol):
    def register(self, descriptor: MachineFamilyDescriptor) -> None: ...
    def get(self, family_id: str) -> MachineFamilyDescriptor: ...
    def list(self) -> tuple[MachineFamilyDescriptor, ...]: ...


class InMemoryMachineFamilyRegistry(MachineFamilyRegistryPort):
    """Strict registry used by composition; duplicate identities are conflicts."""

    def __init__(self) -> None:
        self._items: dict[str, MachineFamilyDescriptor] = {}
        self._lock = RLock()

    def register(self, descriptor: MachineFamilyDescriptor) -> None:
        if not isinstance(descriptor, MachineFamilyDescriptor):
            raise TypeError("machine family registry accepts MachineFamilyDescriptor")
        with self._lock:
            current = self._items.get(descriptor.family_id)
            if current is not None and current != descriptor:
                raise ValueError("machine family identity is already registered")
            self._items[descriptor.family_id] = descriptor

    def get(self, family_id: str) -> MachineFamilyDescriptor:
        if type(family_id) is not str or not family_id.strip():
            raise ValueError("machine family_id is required")
        with self._lock:
            try:
                return self._items[family_id]
            except KeyError as exc:
                raise KeyError(f"unknown machine family: {family_id}") from exc

    def list(self) -> tuple[MachineFamilyDescriptor, ...]:
        with self._lock:
            return tuple(self._items[key] for key in sorted(self._items))


__all__ = [
    "InMemoryMachineFamilyRegistry",
    "MachineFamilyDescriptor",
    "MachineFamilyRegistryPort",
]
