"""Typed contracts for the universal Noetrium research harness.

The harness is a composition boundary: downstream code supplies method nodes and
policies while platform services remain injected, identifiable, and replayable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from noetrium.contracts.json import JsonValue, canonical_digest, freeze_json


class HarnessProfileMode(StrEnum):
    WORKBENCH = "workbench"
    STUDY = "study"


class HarnessNodePhase(StrEnum):
    AUTHOR = "author"
    EXECUTE = "execute"
    OBSERVE = "observe"
    EVALUATE = "evaluate"
    PUBLISH = "publish"


def _names(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if type(values) is not tuple or any(type(value) is not str or not value.strip() for value in values):
        raise TypeError(f"{label} must contain non-empty strings")
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")
    return values


@dataclass(frozen=True, slots=True)
class HarnessPluginSpec:
    """Immutable identity of one replaceable service bundle."""

    plugin_id: str
    revision: str = "1"
    depends_on: tuple[str, ...] = ()
    services: tuple[str, ...] = ()
    plugin_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.plugin_id) is not str or not self.plugin_id.strip():
            raise ValueError("harness plugin_id must be non-empty")
        if type(self.revision) is not str or not self.revision.strip():
            raise ValueError("harness plugin revision must be non-empty")
        depends_on = _names(self.depends_on, "harness plugin dependencies")
        services = _names(self.services, "harness plugin services")
        if self.plugin_id in depends_on:
            raise ValueError("harness plugin cannot depend on itself")
        object.__setattr__(self, "depends_on", depends_on)
        object.__setattr__(self, "services", services)
        object.__setattr__(self, "plugin_digest", canonical_digest({
            "plugin_id": self.plugin_id,
            "revision": self.revision,
            "depends_on": depends_on,
            "services": services,
        }))


@dataclass(frozen=True, slots=True)
class HarnessNodeSpec:
    """Stable identity and dependency declaration for one downstream node."""

    node_id: str
    phase: HarnessNodePhase
    depends_on: tuple[str, ...] = ()
    service_keys: tuple[str, ...] = ()
    node_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.node_id) is not str or not self.node_id.strip():
            raise ValueError("harness node_id must be non-empty")
        if not isinstance(self.phase, HarnessNodePhase):
            raise TypeError("harness node phase must be HarnessNodePhase")
        depends_on = _names(self.depends_on, "harness node dependencies")
        service_keys = _names(self.service_keys, "harness node service keys")
        if self.node_id in depends_on:
            raise ValueError("harness node cannot depend on itself")
        object.__setattr__(self, "depends_on", depends_on)
        object.__setattr__(self, "service_keys", service_keys)
        object.__setattr__(self, "node_digest", canonical_digest({
            "node_id": self.node_id,
            "phase": self.phase.value,
            "depends_on": depends_on,
            "service_keys": service_keys,
        }))


@dataclass(frozen=True, slots=True)
class HarnessProfile:
    """Compiled, auditable selection of plugin and node identities."""

    profile_id: str
    mode: HarnessProfileMode
    plugins: tuple[HarnessPluginSpec, ...] = ()
    nodes: tuple[HarnessNodeSpec, ...] = ()
    profile_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.profile_id) is not str or not self.profile_id.strip():
            raise ValueError("harness profile_id must be non-empty")
        if not isinstance(self.mode, HarnessProfileMode):
            raise TypeError("harness profile mode must be HarnessProfileMode")
        if type(self.plugins) is not tuple or any(type(item) is not HarnessPluginSpec for item in self.plugins):
            raise TypeError("harness profile plugins must contain HarnessPluginSpec")
        if type(self.nodes) is not tuple or any(type(item) is not HarnessNodeSpec for item in self.nodes):
            raise TypeError("harness profile nodes must contain HarnessNodeSpec")
        plugin_ids = tuple(item.plugin_id for item in self.plugins)
        node_ids = tuple(item.node_id for item in self.nodes)
        if len(plugin_ids) != len(set(plugin_ids)):
            raise ValueError("harness profile plugin ids must be unique")
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("harness profile node ids must be unique")
        known_plugins = set(plugin_ids)
        for plugin in self.plugins:
            if any(dep not in known_plugins for dep in plugin.depends_on):
                raise ValueError(f"unknown plugin dependency in {plugin.plugin_id}")
        known_nodes = set(node_ids)
        for node in self.nodes:
            if any(dep not in known_nodes for dep in node.depends_on):
                raise ValueError(f"unknown node dependency in {node.node_id}")
        object.__setattr__(self, "profile_digest", canonical_digest({
            "profile_id": self.profile_id,
            "mode": self.mode.value,
            "plugins": tuple(item.plugin_digest for item in self.plugins),
            "nodes": tuple(item.node_digest for item in self.nodes),
        }))


@dataclass(frozen=True, slots=True)
class HarnessNodeResult:
    node_id: str
    outputs: Mapping[str, JsonValue] = field(default_factory=dict)
    result_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.node_id) is not str or not self.node_id.strip():
            raise ValueError("harness node result node_id must be non-empty")
        if not isinstance(self.outputs, Mapping):
            raise TypeError("harness node result outputs must be a mapping")
        frozen = freeze_json(self.outputs)
        object.__setattr__(self, "outputs", frozen)
        object.__setattr__(self, "result_digest", canonical_digest({
            "node_id": self.node_id,
            "outputs": frozen,
        }))


class HarnessPluginPort(Protocol):
    def install(self, context: object) -> object | None: ...


class HarnessNodePort(Protocol):
    def run(self, context: object, state: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]: ...


__all__ = [
    "HarnessNodePhase",
    "HarnessNodePort",
    "HarnessNodeResult",
    "HarnessNodeSpec",
    "HarnessPluginPort",
    "HarnessPluginSpec",
    "HarnessProfile",
    "HarnessProfileMode",
]
