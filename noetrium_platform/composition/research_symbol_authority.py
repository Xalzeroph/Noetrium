from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.structure import NoetriumUnit


def _sha(value: str, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError(f"{field_name} must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class ResearchSymbolBinding:
    """One exact owner-system binding for a platform-resolved NoetriumUnit."""

    symbol_id: str
    owner_trait_id: str
    symbol_digest: str
    owner_system: str
    provider_identity: str
    binding_identity_digest: str
    binding: object = field(repr=False, compare=False)
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("symbol_id", "owner_trait_id", "owner_system", "provider_identity"):
            value = getattr(self, name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"research symbol binding {name} must be non-empty")
        _sha(self.symbol_digest, "research symbol binding symbol_digest")
        _sha(
            self.binding_identity_digest,
            "research symbol binding binding_identity_digest",
        )
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest(
                {
                    "schema": "noetrium.research-symbol-binding.v1",
                    "symbol_id": self.symbol_id,
                    "owner_trait_id": self.owner_trait_id,
                    "symbol_digest": self.symbol_digest,
                    "owner_system": self.owner_system,
                    "provider_identity": self.provider_identity,
                    "binding_identity_digest": self.binding_identity_digest,
                }
            ),
        )

    def validate_symbol(self, symbol: NoetriumUnit) -> None:
        if type(symbol) is not NoetriumUnit:
            raise TypeError(
                "research symbol binding validation requires NoetriumUnit"
            )
        if symbol.symbol_id != self.symbol_id:
            raise ValueError("research symbol binding symbol_id drifted")
        if symbol.symbol_digest != self.symbol_digest:
            raise ValueError("research symbol binding digest drifted")
        if not symbol.has_trait(self.owner_trait_id):
            raise ValueError(
                "research symbol binding owner trait drifted: "
                f"{self.owner_trait_id}"
            )
        if not symbol.platform_resolved:
            raise ValueError(
                "research symbol binding may only satisfy platform-resolved symbols"
            )


class ResearchSymbolBindingMissing(LookupError):
    def __init__(self, symbol: NoetriumUnit, owner_trait_id: str) -> None:
        if type(symbol) is not NoetriumUnit:
            raise TypeError("missing symbol binding requires NoetriumUnit")
        if type(owner_trait_id) is not str or not owner_trait_id.strip():
            raise ValueError("missing symbol binding owner_trait_id is required")
        self.symbol_id = symbol.symbol_id
        self.owner_trait_id = owner_trait_id
        self.symbol_digest = symbol.symbol_digest
        self.error_digest = canonical_digest(
            {
                "schema": "noetrium.research-symbol-binding-missing.v1",
                "symbol_id": symbol.symbol_id,
                "owner_trait_id": owner_trait_id,
                "symbol_digest": symbol.symbol_digest,
            }
        )
        super().__init__(
            "no exact platform owner binding for "
            f"{owner_trait_id}:{symbol.symbol_id}"
        )


@runtime_checkable
class ResearchSymbolBindingAuthorityPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def resolve(
        self,
        symbol: NoetriumUnit,
        *,
        owner_trait_id: str,
    ) -> ResearchSymbolBinding: ...


class ResearchSymbolBindingRegistry:
    """Immutable exact-symbol registry; no runtime provider selection."""

    def __init__(
        self,
        bindings: tuple[ResearchSymbolBinding, ...],
    ) -> None:
        if type(bindings) is not tuple or any(
            type(row) is not ResearchSymbolBinding for row in bindings
        ):
            raise TypeError("research symbol binding registry requires typed tuple")
        keys = tuple(
            (row.symbol_digest, row.owner_trait_id)
            for row in bindings
        )
        if len(keys) != len(set(keys)):
            raise ValueError(
                "research symbol binding registry contains duplicate exact bindings"
            )
        ordered = tuple(
            sorted(
                bindings,
                key=lambda row: (
                    row.owner_trait_id,
                    row.symbol_id,
                    row.binding_digest,
                ),
            )
        )
        self._bindings = ordered
        self._by_key = {
            (row.symbol_digest, row.owner_trait_id): row
            for row in ordered
        }
        self._identity_digest = canonical_digest(
            {
                "schema": "noetrium.research-symbol-binding-registry.v1",
                "bindings": tuple(row.binding_digest for row in ordered),
            }
        )

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    def resolve(
        self,
        symbol: NoetriumUnit,
        *,
        owner_trait_id: str,
    ) -> ResearchSymbolBinding:
        if type(symbol) is not NoetriumUnit:
            raise TypeError(
                "research symbol binding resolution requires NoetriumUnit"
            )
        if not symbol.platform_resolved:
            raise ValueError(
                "paper-owned symbol must resolve through implementation authority"
            )
        if not symbol.has_trait(owner_trait_id):
            raise ValueError(
                f"research symbol does not declare owner trait {owner_trait_id!r}"
            )
        row = self._by_key.get((symbol.symbol_digest, owner_trait_id))
        if row is None:
            raise ResearchSymbolBindingMissing(symbol, owner_trait_id)
        row.validate_symbol(symbol)
        return row

    @property
    def bindings(self) -> tuple[ResearchSymbolBinding, ...]:
        return self._bindings


__all__ = [
    "ResearchSymbolBinding",
    "ResearchSymbolBindingAuthorityPort",
    "ResearchSymbolBindingMissing",
    "ResearchSymbolBindingRegistry",
]
