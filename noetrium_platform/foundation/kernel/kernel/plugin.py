"""Versioned plugin manifests and permission-neutral registry."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .canonical import canonical_digest, require_sha256


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"plugin {field_name} must be non-empty text")
    return value


def _items(value: object, field_name: str) -> tuple[str, ...]:
    if type(value) is not tuple or any(type(item) is not str or not item.strip() for item in value):
        raise TypeError(f"plugin {field_name} must be a text tuple")
    if tuple(sorted(set(value))) != value:
        raise ValueError(f"plugin {field_name} must be ordered and unique")
    return value


@dataclass(frozen=True, slots=True)
class PluginManifest:
    plugin_id: str
    plugin_version: str
    api_version: str
    machine_kinds: tuple[str, ...]
    capabilities: tuple[str, ...]
    input_schemas: tuple[str, ...]
    output_schemas: tuple[str, ...]
    effect_classes: tuple[str, ...]
    resource_requirements: tuple[str, ...]
    replay_level: str
    security_policy: str
    signature_digest: str | None = None
    manifest_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("plugin_id", self.plugin_id),
            ("plugin_version", self.plugin_version),
            ("api_version", self.api_version),
            ("replay_level", self.replay_level),
            ("security_policy", self.security_policy),
        ):
            _text(value, name)
        for name, value in (
            ("machine_kinds", self.machine_kinds),
            ("capabilities", self.capabilities),
            ("input_schemas", self.input_schemas),
            ("output_schemas", self.output_schemas),
            ("effect_classes", self.effect_classes),
            ("resource_requirements", self.resource_requirements),
        ):
            _items(value, name)
        if self.signature_digest is not None:
            require_sha256(self.signature_digest, "signature_digest")
        object.__setattr__(self, "manifest_digest", canonical_digest(self.as_dict()))

    def as_dict(self) -> dict[str, object]:
        return {
            "plugin_id": self.plugin_id,
            "plugin_version": self.plugin_version,
            "api_version": self.api_version,
            "machine_kinds": self.machine_kinds,
            "capabilities": self.capabilities,
            "input_schemas": self.input_schemas,
            "output_schemas": self.output_schemas,
            "effect_classes": self.effect_classes,
            "resource_requirements": self.resource_requirements,
            "replay_level": self.replay_level,
            "security_policy": self.security_policy,
            "signature_digest": self.signature_digest,
        }


@runtime_checkable
class PluginRegistryPort(Protocol):
    def register(self, manifest: PluginManifest) -> None: ...
    def get(self, plugin_id: str) -> PluginManifest: ...
    def list(self) -> tuple[PluginManifest, ...]: ...


@runtime_checkable
class PluginSignatureVerifier(Protocol):
    def verify(self, manifest: PluginManifest) -> bool: ...


class InMemoryPluginRegistry(PluginRegistryPort):
    """Stores declarations only; registration never grants runtime permission."""

    def __init__(self, verifier: PluginSignatureVerifier | None = None) -> None:
        if verifier is not None and not isinstance(verifier, PluginSignatureVerifier):
            raise TypeError("plugin verifier must implement PluginSignatureVerifier")
        self._items: dict[str, PluginManifest] = {}
        self._verifier = verifier

    def register(self, manifest: PluginManifest) -> None:
        if not isinstance(manifest, PluginManifest):
            raise TypeError("plugin registry accepts PluginManifest")
        if self._verifier is not None and not self._verifier.verify(manifest):
            raise ValueError("plugin manifest signature was rejected")
        current = self._items.get(manifest.plugin_id)
        if current is not None and current != manifest:
            raise ValueError("plugin identity is already registered")
        self._items[manifest.plugin_id] = manifest

    def get(self, plugin_id: str) -> PluginManifest:
        _text(plugin_id, "plugin_id")
        try:
            return self._items[plugin_id]
        except KeyError as exc:
            raise KeyError(f"unknown plugin: {plugin_id}") from exc

    def list(self) -> tuple[PluginManifest, ...]:
        return tuple(self._items[key] for key in sorted(self._items))


__all__ = [
    "InMemoryPluginRegistry",
    "PluginManifest",
    "PluginRegistryPort",
    "PluginSignatureVerifier",
]
