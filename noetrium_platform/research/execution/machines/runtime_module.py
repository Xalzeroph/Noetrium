"""Runtime-module semantic schema over the shared NoetriumUnit kernel.

A module is not a parallel IR. It is a NoetriumUnit tagged ``runtime.module``;
its children are the same ``machine.operation`` graphs used by Machine programs.
Runtime-program composition is therefore a pure Unit -> Unit transform.
"""
from __future__ import annotations

from noetrium_platform.foundation.kernel.structure import endpoint_unit, relation_unit, structure_unit

from collections.abc import Mapping

from noetrium_platform.foundation.kernel.structure import (
    NoetriumUnit,
)
from noetrium_platform.foundation.kernel.kernel import JsonObject, JsonValue, thaw_json
from .domains import RuntimeConcern
from noetrium_platform.foundation.kernel.kernel.universal import (
    unit_operation_configuration,
    unit_operation_name,
    unit_operation_required_capabilities,
    unit_flow,
    unit_operation,
    executable_unit,
)

RUNTIME_MODULE_TRAIT = "runtime.module"
RUNTIME_MODULE_FLOW_RELATION = "runtime.module.flow"


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


def validate_runtime_module(module: NoetriumUnit) -> None:
    if type(module) is not NoetriumUnit or not module.has_trait(RUNTIME_MODULE_TRAIT):
        raise TypeError("runtime module must be a runtime.module NoetriumUnit")
    concern = module.parameters.get("concern")
    RuntimeConcern(_text(concern, "runtime module concern"))
    entrypoint = _text(module.parameters.get("entrypoint"), "runtime module entrypoint")
    module.member(entrypoint)
    for child in module.members:
        unit_operation_name(child)
    for relation in module.relations:
        if relation.relation_id != RUNTIME_MODULE_FLOW_RELATION:
            continue
        if relation.sources[0].child_id is None or relation.targets[0].child_id is None:
            raise ValueError("runtime.module.flow must connect operation graphs")
        module.member(relation.sources[0].child_id)
        module.member(relation.targets[0].child_id)


def runtime_module_concern(module: NoetriumUnit) -> RuntimeConcern:
    validate_runtime_module(module)
    return RuntimeConcern(str(module.parameters["concern"]))


def runtime_module_entrypoint(module: NoetriumUnit) -> str:
    validate_runtime_module(module)
    return str(module.parameters["entrypoint"])


def runtime_module_nodes(module: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    validate_runtime_module(module)
    return module.members


def runtime_module_node(module: NoetriumUnit, node_id: str) -> NoetriumUnit:
    validate_runtime_module(module)
    return module.member(_text(node_id, "runtime module operation id"))


def runtime_module_next_node(module: NoetriumUnit, node: NoetriumUnit) -> str | None:
    validate_runtime_module(module)
    targets = tuple(
        relation.targets[0].child_id
        for relation in module.relations
        if relation.relation_id == RUNTIME_MODULE_FLOW_RELATION
        and relation.sources[0].child_id == node.unit_id
        and relation.targets[0].child_id is not None
    )
    if len(targets) > 1:
        raise ValueError("runtime module operation has multiple successors")
    return None if not targets else targets[0]


def runtime_module_exit_nodes(module: NoetriumUnit) -> tuple[str, ...]:
    validate_runtime_module(module)
    sources = {
        relation.sources[0].child_id
        for relation in module.relations
        if relation.relation_id == RUNTIME_MODULE_FLOW_RELATION
        and relation.sources[0].child_id is not None
    }
    return tuple(child.unit_id for child in module.members if child.unit_id not in sources)


def runtime_module(
    *,
    module_id: str,
    concern: RuntimeConcern,
    entrypoint: str,
    nodes: tuple[NoetriumUnit, ...],
    links: tuple[tuple[str, str], ...] = (),
) -> NoetriumUnit:
    """Construct one immutable runtime.module Unit directly."""

    module_id = _text(module_id, "runtime module_id")
    if not isinstance(concern, RuntimeConcern):
        raise TypeError("runtime module concern must be RuntimeConcern")
    entrypoint = _text(entrypoint, "runtime module entrypoint")
    if type(nodes) is not tuple or not nodes:
        raise ValueError("runtime module requires operation Units")
    for node in nodes:
        unit_operation_name(node)
    ids = tuple(node.unit_id for node in nodes)
    if len(ids) != len(set(ids)):
        raise ValueError("runtime module operation ids must be unique")
    if entrypoint not in ids:
        raise ValueError("runtime module entrypoint does not exist")
    id_set = set(ids)
    relations: list[NoetriumUnit] = []
    for source, target in links:
        source = _text(source, "runtime module link source")
        target = _text(target, "runtime module link target")
        if source not in id_set or target not in id_set:
            raise ValueError("runtime module link references unknown operation")
        relations.append(
            relation_unit(
                (endpoint_unit(source, None),),
                (endpoint_unit(target, None),),
                RUNTIME_MODULE_FLOW_RELATION,
            )
        )
    module = structure_unit(
        module_id,
        traits=(RUNTIME_MODULE_TRAIT,),
        parameters={"concern": concern.value, "entrypoint": entrypoint},
        members=nodes,
        relations=tuple(relations),
    )
    validate_runtime_module(module)
    return module


def compose_runtime_program(
    *,
    program_id: str,
    version: str,
    state_schema: str,
    entry_module: str,
    modules: tuple[NoetriumUnit, ...],
    entry_node: str | None = None,
    required_capabilities: tuple[str, ...] = (),
    links: tuple[tuple[str, str, str, str | None], ...] = (),
) -> NoetriumUnit:
    """Pure Graph -> Graph transform from runtime modules to machine.program."""

    program_id = _text(program_id, "runtime program_id")
    version = _text(version, "runtime program version")
    state_schema = _text(state_schema, "runtime program state_schema")
    entry_module = _text(entry_module, "runtime entry_module")
    entry_node = None if entry_node is None else _text(entry_node, "runtime entry_node")
    if type(modules) is not tuple or not modules:
        raise ValueError("runtime program requires modules")
    module_map: dict[str, NoetriumUnit] = {}
    for module in modules:
        validate_runtime_module(module)
        if module.unit_id in module_map:
            raise ValueError(f"duplicate runtime module id: {module.unit_id}")
        module_map[module.unit_id] = module
    root = module_map.get(entry_module)
    if root is None:
        raise ValueError("runtime entry module is not registered")
    resolved_entry = entry_node or runtime_module_entrypoint(root)
    runtime_module_node(root, resolved_entry)

    external: dict[tuple[str, str], tuple[str, str | None]] = {}
    for source_module, source_node, target_module, target_node in links:
        key = (
            _text(source_module, "runtime link source_module"),
            _text(source_node, "runtime link source_node"),
        )
        if key in external:
            raise ValueError("runtime module exit is already linked")
        external[key] = (
            _text(target_module, "runtime link target_module"),
            None if target_node is None else _text(target_node, "runtime link target_node"),
        )

    members: list[NoetriumUnit] = []
    relations: list[NoetriumUnit] = []
    def qualified(module_id: str, node_id: str) -> str:
        return f"{module_id}.{node_id}"

    for module_id in sorted(module_map):
        module = module_map[module_id]
        for node in runtime_module_nodes(module):
            local_next = runtime_module_next_node(module, node)
            link = external.get((module_id, node.unit_id))
            if local_next is not None and link is not None:
                raise ValueError(
                    "runtime links may bind only module exit operations; "
                    f"{module_id}.{node.unit_id} already has a local successor"
                )
            if local_next is not None:
                next_node = qualified(module_id, local_next)
            elif link is not None:
                target_module_id, target_node_id = link
                target = module_map.get(target_module_id)
                if target is None:
                    raise ValueError(
                        f"runtime link target module does not exist: {target_module_id}"
                    )
                target_id = target_node_id or runtime_module_entrypoint(target)
                runtime_module_node(target, target_id)
                next_node = qualified(target_module_id, target_id)
            else:
                next_node = None
            configuration = dict(thaw_json(unit_operation_configuration(node)))
            configuration["runtime_module"] = module.unit_id
            configuration["runtime_module_digest"] = module.unit_digest
            configuration["runtime_concern"] = runtime_module_concern(module).value
            node_id = qualified(module_id, node.unit_id)
            members.append(
                unit_operation(
                    node_id,
                    unit_operation_name(node),
                    configuration=configuration,
                    required_capabilities=unit_operation_required_capabilities(node),
                )
            )
            if next_node is not None:
                relations.append(unit_flow(node_id, next_node, default=True))

    return executable_unit(
        program_id,
        domain="runtime",
        version=version,
        state_schema=state_schema,
        entrypoint=qualified(entry_module, resolved_entry),
        required_capabilities=required_capabilities,
        members=tuple(members),
        relations=tuple(relations),
    )


__all__ = [
    "RUNTIME_MODULE_FLOW_RELATION",
    "RUNTIME_MODULE_TRAIT",
            "runtime_module",
    "compose_runtime_program",
    "runtime_module_concern",
    "runtime_module_entrypoint",
    "runtime_module_exit_nodes",
    "runtime_module_next_node",
    "runtime_module_node",
    "runtime_module_nodes",
    "validate_runtime_module",
]
