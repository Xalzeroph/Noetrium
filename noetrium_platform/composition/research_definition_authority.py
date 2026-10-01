from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.product.research_os import (
    ResearchDefinition,
    ResearchDefinitionKind,
)


def _sha(value: str, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError(f"{field_name} must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class ResearchDefinitionBinding:
    """One exact owner-system binding for a platform-resolved definition."""

    definition_id: str
    kind: ResearchDefinitionKind
    definition_digest: str
    owner_system: str
    provider_identity: str
    binding_identity_digest: str
    binding: object = field(repr=False, compare=False)
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.definition_id) is not str or not self.definition_id.strip():
            raise ValueError("definition binding definition_id must be non-empty")
        if not isinstance(self.kind, ResearchDefinitionKind):
            raise TypeError("definition binding kind must be typed")
        _sha(self.definition_digest, "definition binding definition_digest")
        for name in ("owner_system", "provider_identity"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"definition binding {name} must be non-empty")
        _sha(
            self.binding_identity_digest,
            "definition binding binding_identity_digest",
        )
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest(
                {
                    "schema": "noetrium.research-definition-binding.v1",
                    "definition_id": self.definition_id,
                    "kind": self.kind.value,
                    "definition_digest": self.definition_digest,
                    "owner_system": self.owner_system,
                    "provider_identity": self.provider_identity,
                    "binding_identity_digest": self.binding_identity_digest,
                }
            ),
        )

    def validate_definition(self, definition: ResearchDefinition) -> None:
        if type(definition) is not ResearchDefinition:
            raise TypeError("definition binding validation requires ResearchDefinition")
        if definition.definition_id != self.definition_id:
            raise ValueError("definition binding definition_id drifted")
        if definition.kind is not self.kind:
            raise ValueError("definition binding kind drifted")
        if definition.definition_digest != self.definition_digest:
            raise ValueError("definition binding definition digest drifted")
        if not definition.platform_resolved:
            raise ValueError(
                "definition binding may only satisfy platform-resolved definitions"
            )


class ResearchDefinitionBindingMissing(LookupError):
    def __init__(self, definition: ResearchDefinition) -> None:
        if type(definition) is not ResearchDefinition:
            raise TypeError("missing definition binding requires ResearchDefinition")
        self.definition_id = definition.definition_id
        self.kind = definition.kind
        self.definition_digest = definition.definition_digest
        self.error_digest = canonical_digest(
            {
                "schema": "noetrium.research-definition-binding-missing.v1",
                "definition_id": definition.definition_id,
                "kind": definition.kind.value,
                "definition_digest": definition.definition_digest,
            }
        )
        super().__init__(
            "no exact platform owner binding for "
            f"{definition.kind.value}:{definition.definition_id}"
        )


@runtime_checkable
class ResearchDefinitionBindingAuthorityPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def resolve(
        self,
        definition: ResearchDefinition,
    ) -> ResearchDefinitionBinding: ...


class ResearchDefinitionBindingRegistry:
    """Immutable exact-definition registry; no runtime provider selection."""

    def __init__(
        self,
        bindings: tuple[ResearchDefinitionBinding, ...],
    ) -> None:
        if type(bindings) is not tuple or any(
            type(row) is not ResearchDefinitionBinding for row in bindings
        ):
            raise TypeError("definition binding registry requires typed tuple")
        keys = tuple(row.definition_digest for row in bindings)
        if len(keys) != len(set(keys)):
            raise ValueError("definition binding registry contains duplicate definitions")
        ordered = tuple(
            sorted(
                bindings,
                key=lambda row: (
                    row.kind.value,
                    row.definition_id,
                    row.binding_digest,
                ),
            )
        )
        self._bindings = ordered
        self._by_digest = {
            row.definition_digest: row for row in ordered
        }
        self._identity_digest = canonical_digest(
            {
                "schema": "noetrium.research-definition-binding-registry.v1",
                "bindings": tuple(row.binding_digest for row in ordered),
            }
        )

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    def resolve(
        self,
        definition: ResearchDefinition,
    ) -> ResearchDefinitionBinding:
        if type(definition) is not ResearchDefinition:
            raise TypeError(
                "definition binding resolution requires ResearchDefinition"
            )
        if not definition.platform_resolved:
            raise ValueError(
                "paper-owned definition must resolve through implementation authority"
            )
        row = self._by_digest.get(definition.definition_digest)
        if row is None:
            raise ResearchDefinitionBindingMissing(definition)
        row.validate_definition(definition)
        return row

    @property
    def bindings(self) -> tuple[ResearchDefinitionBinding, ...]:
        return self._bindings


__all__ = [
    "ResearchDefinitionBinding",
    "ResearchDefinitionBindingAuthorityPort",
    "ResearchDefinitionBindingMissing",
    "ResearchDefinitionBindingRegistry",
]
