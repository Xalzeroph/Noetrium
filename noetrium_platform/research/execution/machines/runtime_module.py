"""Composable subprogram IR for Universal Runtime Machine semantics.

A RuntimeProgram need not be authored as one monolithic graph. Downstream
research can define only the concern it changes (context, communication,
logical scheduling, synchronization, capability mediation, recovery, intervention, etc.) and
compose that module with unchanged modules from another preset.

Modules are compile-time structure only. They own no runtime state, journal,
or authority. Composition produces one ordinary ResearchProgram executed by
the shared Machine substrate.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from noetrium_platform.foundation.kernel.kernel import JsonObject, freeze_json, thaw_json
from .domains import RuntimeConcern, RuntimeProgramBuilder
from .program import ProgramNode, ResearchProgram


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


@dataclass(frozen=True, slots=True)
class RuntimeModuleNode:
    node_id: str
    operation: str
    configuration: JsonObject = field(default_factory=dict)
    next_node: str | None = None
    required_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _text(self.node_id, "runtime module node_id"))
        object.__setattr__(self, "operation", _text(self.operation, "runtime module operation"))
        if not isinstance(self.configuration, Mapping):
            raise TypeError("runtime module node configuration must be an object")
        if self.next_node is not None:
            object.__setattr__(
                self,
                "next_node",
                _text(self.next_node, "runtime module next_node"),
            )
        if type(self.required_capabilities) is not tuple or any(
            type(value) is not str or not value.strip()
            for value in self.required_capabilities
        ):
            raise TypeError(
                "runtime module required_capabilities must be a text tuple"
            )
        if len(self.required_capabilities) != len(set(self.required_capabilities)):
            raise ValueError(
                "runtime module required_capabilities must be unique"
            )
        object.__setattr__(
            self,
            "configuration",
            freeze_json(self.configuration),
        )


@dataclass(frozen=True, slots=True)
class RuntimeModule:
    module_id: str
    concern: RuntimeConcern
    entrypoint: str
    nodes: tuple[RuntimeModuleNode, ...]
    module_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "module_id",
            _text(self.module_id, "runtime module_id"),
        )
        if not isinstance(self.concern, RuntimeConcern):
            raise TypeError("runtime module concern must be RuntimeConcern")
        object.__setattr__(
            self,
            "entrypoint",
            _text(self.entrypoint, "runtime module entrypoint"),
        )
        if type(self.nodes) is not tuple or not self.nodes:
            raise ValueError("runtime module requires at least one node")
        if any(not isinstance(node, RuntimeModuleNode) for node in self.nodes):
            raise TypeError("runtime module nodes must be RuntimeModuleNode")
        mapping = {node.node_id: node for node in self.nodes}
        if len(mapping) != len(self.nodes):
            raise ValueError("runtime module node ids must be unique")
        if self.entrypoint not in mapping:
            raise ValueError("runtime module entrypoint does not exist")
        missing = sorted({
            node.next_node
            for node in self.nodes
            if node.next_node is not None and node.next_node not in mapping
        })
        if missing:
            raise ValueError(
                f"runtime module references missing local nodes: {missing}"
            )
        from noetrium_platform.foundation.kernel.kernel import canonical_digest
        object.__setattr__(
            self,
            "module_digest",
            canonical_digest({
                "module_id": self.module_id,
                "concern": self.concern.value,
                "entrypoint": self.entrypoint,
                "nodes": tuple({
                    "node_id": node.node_id,
                    "operation": node.operation,
                    "configuration": thaw_json(node.configuration),
                    "next_node": node.next_node,
                    "required_capabilities": node.required_capabilities,
                } for node in self.nodes),
            }),
        )

    @property
    def exit_nodes(self) -> tuple[str, ...]:
        return tuple(
            node.node_id for node in self.nodes if node.next_node is None
        )

    def node(self, node_id: str) -> RuntimeModuleNode:
        node_id = _text(node_id, "runtime module node_id")
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise KeyError(node_id)


class RuntimeModuleBuilder:
    def __init__(
        self,
        *,
        module_id: str,
        concern: RuntimeConcern,
        entrypoint: str,
    ) -> None:
        self._module_id = _text(module_id, "runtime module_id")
        if not isinstance(concern, RuntimeConcern):
            raise TypeError("runtime module concern must be RuntimeConcern")
        self._concern = concern
        self._entrypoint = _text(entrypoint, "runtime module entrypoint")
        self._nodes: list[RuntimeModuleNode] = []

    @classmethod
    def context(cls, *, module_id: str, entrypoint: str) -> "RuntimeModuleBuilder":
        return cls(module_id=module_id, concern=RuntimeConcern.CONTEXT, entrypoint=entrypoint)

    @classmethod
    def communication(cls, *, module_id: str, entrypoint: str) -> "RuntimeModuleBuilder":
        return cls(module_id=module_id, concern=RuntimeConcern.COMMUNICATION, entrypoint=entrypoint)

    @classmethod
    def scheduling(cls, *, module_id: str, entrypoint: str) -> "RuntimeModuleBuilder":
        return cls(module_id=module_id, concern=RuntimeConcern.LOGICAL_SCHEDULING, entrypoint=entrypoint)

    @classmethod
    def synchronization(cls, *, module_id: str, entrypoint: str) -> "RuntimeModuleBuilder":
        return cls(
            module_id=module_id,
            concern=RuntimeConcern.SYNCHRONIZATION,
            entrypoint=entrypoint,
        )

    @classmethod
    def capability(cls, *, module_id: str, entrypoint: str) -> "RuntimeModuleBuilder":
        return cls(module_id=module_id, concern=RuntimeConcern.CAPABILITY_MEDIATION, entrypoint=entrypoint)

    @classmethod
    def recovery(cls, *, module_id: str, entrypoint: str) -> "RuntimeModuleBuilder":
        return cls(module_id=module_id, concern=RuntimeConcern.RECOVERY, entrypoint=entrypoint)

    @classmethod
    def intervention(cls, *, module_id: str, entrypoint: str) -> "RuntimeModuleBuilder":
        return cls(module_id=module_id, concern=RuntimeConcern.INTERVENTION, entrypoint=entrypoint)

    @classmethod
    def turn(cls, *, module_id: str, entrypoint: str) -> "RuntimeModuleBuilder":
        return cls(module_id=module_id, concern=RuntimeConcern.TURN, entrypoint=entrypoint)

    @classmethod
    def event(cls, *, module_id: str, entrypoint: str) -> "RuntimeModuleBuilder":
        return cls(module_id=module_id, concern=RuntimeConcern.EVENT, entrypoint=entrypoint)

    @classmethod
    def visibility(cls, *, module_id: str, entrypoint: str) -> "RuntimeModuleBuilder":
        return cls(module_id=module_id, concern=RuntimeConcern.VISIBILITY, entrypoint=entrypoint)

    def node(
        self,
        node_id: str,
        operation: str,
        *,
        configuration: JsonObject | None = None,
        next_node: str | None = None,
        required_capabilities: tuple[str, ...] = (),
    ) -> "RuntimeModuleBuilder":
        self._nodes.append(
            RuntimeModuleNode(
                node_id=node_id,
                operation=operation,
                configuration={} if configuration is None else configuration,
                next_node=next_node,
                required_capabilities=required_capabilities,
            )
        )
        return self

    def build(self) -> RuntimeModule:
        return RuntimeModule(
            module_id=self._module_id,
            concern=self._concern,
            entrypoint=self._entrypoint,
            nodes=tuple(self._nodes),
        )


@dataclass(frozen=True, slots=True)
class RuntimeModuleLink:
    source_module: str
    source_node: str
    target_module: str
    target_node: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("source_module", "source_node", "target_module"):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), f"runtime link {field_name}"),
            )
        if self.target_node is not None:
            object.__setattr__(
                self,
                "target_node",
                _text(self.target_node, "runtime link target_node"),
            )


class RuntimeProgramComposer:
    """Compose independently-authored RuntimeModules into one RuntimeProgram."""

    def __init__(
        self,
        *,
        program_id: str,
        version: str,
        state_schema: str,
        entry_module: str,
        entry_node: str | None = None,
        required_capabilities: tuple[str, ...] = (),
    ) -> None:
        self._program_id = _text(program_id, "runtime program_id")
        self._version = _text(version, "runtime program version")
        self._state_schema = _text(state_schema, "runtime program state_schema")
        self._entry_module = _text(entry_module, "runtime entry_module")
        self._entry_node = (
            None if entry_node is None else _text(entry_node, "runtime entry_node")
        )
        self._required_capabilities = required_capabilities
        self._modules: dict[str, RuntimeModule] = {}
        self._links: dict[tuple[str, str], RuntimeModuleLink] = {}

    def module(self, module: RuntimeModule) -> "RuntimeProgramComposer":
        if not isinstance(module, RuntimeModule):
            raise TypeError("runtime composer requires RuntimeModule")
        if module.module_id in self._modules:
            raise ValueError(f"duplicate runtime module id: {module.module_id}")
        self._modules[module.module_id] = module
        return self

    def link(
        self,
        source_module: str,
        source_node: str,
        target_module: str,
        *,
        target_node: str | None = None,
    ) -> "RuntimeProgramComposer":
        link = RuntimeModuleLink(
            source_module,
            source_node,
            target_module,
            target_node,
        )
        key = (link.source_module, link.source_node)
        if key in self._links:
            raise ValueError(
                f"runtime module exit is already linked: {key[0]}.{key[1]}"
            )
        self._links[key] = link
        return self

    @staticmethod
    def _qualified(module_id: str, node_id: str) -> str:
        return f"{module_id}.{node_id}"

    def build(self) -> ResearchProgram:
        if not self._modules:
            raise ValueError("runtime program composer requires modules")
        entry_module = self._modules.get(self._entry_module)
        if entry_module is None:
            raise ValueError("runtime entry module is not registered")
        entry_node = self._entry_node or entry_module.entrypoint
        entry_module.node(entry_node)

        for link in self._links.values():
            source = self._modules.get(link.source_module)
            target = self._modules.get(link.target_module)
            if source is None:
                raise ValueError(
                    f"runtime link source module does not exist: {link.source_module}"
                )
            if target is None:
                raise ValueError(
                    f"runtime link target module does not exist: {link.target_module}"
                )
            source_node = source.node(link.source_node)
            if source_node.next_node is not None:
                raise ValueError(
                    "runtime links may bind only module exit nodes; "
                    f"{link.source_module}.{link.source_node} already has a local successor"
                )
            target.node(link.target_node or target.entrypoint)

        builder = RuntimeProgramBuilder.create(
            program_id=self._program_id,
            version=self._version,
            state_schema=self._state_schema,
            entrypoint=self._qualified(self._entry_module, entry_node),
            required_capabilities=self._required_capabilities,
        )
        for module_id in sorted(self._modules):
            module = self._modules[module_id]
            for node in module.nodes:
                link = self._links.get((module_id, node.node_id))
                if node.next_node is not None:
                    next_node = self._qualified(module_id, node.next_node)
                elif link is not None:
                    target = self._modules[link.target_module]
                    next_node = self._qualified(
                        link.target_module,
                        link.target_node or target.entrypoint,
                    )
                else:
                    next_node = None
                configuration = dict(thaw_json(node.configuration))
                configuration["runtime_module"] = module.module_id
                configuration["runtime_module_digest"] = module.module_digest
                builder.semantic(
                    self._qualified(module_id, node.node_id),
                    module.concern,
                    node.operation,
                    configuration=configuration,
                    next_node=next_node,
                    required_capabilities=node.required_capabilities,
                )
        return builder.build()


__all__ = [
    "RuntimeModule",
    "RuntimeModuleBuilder",
    "RuntimeModuleLink",
    "RuntimeModuleNode",
    "RuntimeProgramComposer",
]
