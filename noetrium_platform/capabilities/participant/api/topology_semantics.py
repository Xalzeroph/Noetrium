from __future__ import annotations

"""Recursive participant topology over the single NoetriumUnit universe.

The topology is an arbitrary directed hypergraph.  Dependency relations are
only one projection used to derive execution frontiers; communication,
supervision, feedback, shared-state, and paper-specific relations never force
the scientific topology to be a DAG.
"""

from collections.abc import Mapping
from functools import lru_cache

from noetrium_platform.foundation.kernel.kernel import JsonValue
from noetrium_platform.foundation.kernel.structure import (
    NoetriumUnit,
    strongly_connected_components,
    endpoint_child_id,
    endpoint_port_name,
    endpoint_unit,
    relation_id,
    relation_unit,
    structure_unit,
)

PARTICIPANT_GRAPH_TRAIT = "participant.topology"
PARTICIPANT_VERTEX_TRAIT = "participant.member"
PARTICIPANT_DEPENDENCY_RELATION = "participant.depends-on"
PARTICIPANT_COMMUNICATION_RELATION = "participant.communication"
PARTICIPANT_SUPERVISION_RELATION = "participant.supervision"
PARTICIPANT_SHARED_STATE_RELATION = "participant.shared-state"
PARTICIPANT_FEEDBACK_RELATION = "participant.feedback"


def _role(value: object, field: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be canonical non-empty text")
    return value


def participant_relation(
    sources: tuple[str, ...],
    targets: tuple[str, ...],
    relation_semantic: str,
    *,
    parameters: Mapping[str, JsonValue] | None = None,
) -> NoetriumUnit:
    """Create an arbitrary participant hyperrelation."""

    if type(sources) is not tuple or not sources:
        raise ValueError("participant relation requires source roles")
    if type(targets) is not tuple or not targets:
        raise ValueError("participant relation requires target roles")
    sources = tuple(_role(row, "participant relation source") for row in sources)
    targets = tuple(_role(row, "participant relation target") for row in targets)
    if len(sources) != len(set(sources)) or len(targets) != len(set(targets)):
        raise ValueError("participant relation endpoints must be unique")
    relation_semantic = _role(relation_semantic, "participant relation semantic")
    return relation_unit(
        tuple(endpoint_unit(role, None) for role in sources),
        tuple(endpoint_unit(role, None) for role in targets),
        relation_semantic,
        {} if parameters is None else dict(parameters),
    )


def participant_dependency(
    dependency_role: str,
    dependent_role: str,
) -> NoetriumUnit:
    dependency_role = _role(dependency_role, "participant dependency source role")
    dependent_role = _role(dependent_role, "participant dependency target role")
    if dependency_role == dependent_role:
        raise ValueError("participant cannot scheduling-depend on itself")
    return participant_relation(
        (dependency_role,),
        (dependent_role,),
        PARTICIPANT_DEPENDENCY_RELATION,
    )


def participant_communication(
    sources: tuple[str, ...],
    targets: tuple[str, ...],
    *,
    channel: str | None = None,
    parameters: Mapping[str, JsonValue] | None = None,
) -> NoetriumUnit:
    payload = dict(parameters or {})
    if channel is not None:
        payload["channel"] = _role(channel, "participant communication channel")
    return participant_relation(
        sources,
        targets,
        PARTICIPANT_COMMUNICATION_RELATION,
        parameters=payload,
    )


def participant_graph(
    roles: tuple[str, ...],
    relations: tuple[NoetriumUnit, ...] = (),
) -> NoetriumUnit:
    if type(roles) is not tuple or any(
        type(role) is not str or not role.strip() for role in roles
    ):
        raise TypeError("participant roles must be a text tuple")
    roles = tuple(sorted(_role(role, "participant role") for role in roles))
    if len(roles) != len(set(roles)):
        raise ValueError("participant roles must be unique")
    if type(relations) is not tuple or any(
        type(row) is not NoetriumUnit for row in relations
    ):
        raise TypeError("participant relations must be NoetriumUnit tuple")
    digests = tuple(row.unit_digest for row in relations)
    if len(digests) != len(set(digests)):
        raise ValueError("participant relations must be unique")
    relations = tuple(sorted(relations, key=lambda row: row.unit_digest))
    graph = structure_unit(
        "participant-topology",
        traits=(PARTICIPANT_GRAPH_TRAIT,),
        members=tuple(
            structure_unit(role, traits=(PARTICIPANT_VERTEX_TRAIT,))
            for role in roles
        ),
        relations=relations,
    )
    validate_participant_graph(graph)
    return graph


@lru_cache(maxsize=4096)
def validate_participant_graph(graph: NoetriumUnit) -> tuple[str, ...]:
    """Validate topology shape without imposing a global acyclicity restriction."""

    if (
        type(graph) is not NoetriumUnit
        or not graph.has_trait(PARTICIPANT_GRAPH_TRAIT)
    ):
        raise TypeError(
            "participant topology must be participant.topology NoetriumUnit"
        )
    if any(
        not child.has_trait(PARTICIPANT_VERTEX_TRAIT)
        for child in graph.members
    ):
        raise TypeError(
            "participant topology children must have participant.member trait"
        )
    roles = tuple(sorted(child.unit_id for child in graph.members))
    role_set = frozenset(roles)
    if len(roles) != len(role_set):
        raise ValueError("participant topology roles must be unique")

    seen: set[str] = set()
    for relation in graph.relations:
        if relation.unit_digest in seen:
            raise ValueError("participant topology relations must be unique")
        seen.add(relation.unit_digest)
        endpoints = relation.units("source") + relation.units("target")
        if not endpoints:
            raise ValueError("participant topology relation requires endpoints")
        for endpoint in endpoints:
            child_id = endpoint_child_id(endpoint)
            if child_id is None or child_id not in role_set:
                raise ValueError(
                    "participant topology relation references unknown participant"
                )
            if endpoint_port_name(endpoint) is not None:
                raise ValueError(
                    "participant topology semantic relation cannot bind execution ports"
                )
    return roles


def participant_roles(graph: NoetriumUnit) -> tuple[str, ...]:
    return validate_participant_graph(graph)


@lru_cache(maxsize=4096)
def _dependency_adjacency(
    graph: NoetriumUnit,
) -> dict[str, tuple[str, ...]]:
    roles = validate_participant_graph(graph)
    adjacency: dict[str, set[str]] = {role: set() for role in roles}
    for relation in graph.relations:
        if relation_id(relation) != PARTICIPANT_DEPENDENCY_RELATION:
            continue
        sources = tuple(
            endpoint_child_id(endpoint)
            for endpoint in relation.units("source")
        )
        targets = tuple(
            endpoint_child_id(endpoint)
            for endpoint in relation.units("target")
        )
        for source in sources:
            for target in targets:
                assert source is not None and target is not None
                adjacency[source].add(target)
    return {
        role: tuple(sorted(targets))
        for role, targets in adjacency.items()
    }


@lru_cache(maxsize=4096)
def participant_coordination_components(
    graph: NoetriumUnit,
) -> tuple[tuple[str, ...], ...]:
    """Return dependency SCCs; cyclic groups are native coordination components."""

    roles = validate_participant_graph(graph)
    adjacency = _dependency_adjacency(graph)
    components = strongly_connected_components(roles, adjacency)
    return tuple(
        sorted(
            (tuple(sorted(component)) for component in components),
            key=lambda component: component,
        )
    )


@lru_cache(maxsize=4096)
def participant_waves(
    graph: NoetriumUnit,
) -> tuple[tuple[str, ...], ...]:
    """Derive deterministic execution frontiers from the dependency projection.

    Cyclic dependency regions are collapsed to SCCs.  Non-dependency topology
    relations never constrain scheduling.
    """

    roles = validate_participant_graph(graph)
    if not roles:
        return ()
    adjacency = _dependency_adjacency(graph)
    components = participant_coordination_components(graph)
    component_of = {
        role: index
        for index, component in enumerate(components)
        for role in component
    }
    outgoing: dict[int, set[int]] = {index: set() for index in range(len(components))}
    incoming: dict[int, int] = {index: 0 for index in range(len(components))}
    for source, targets in adjacency.items():
        source_component = component_of[source]
        for target in targets:
            target_component = component_of[target]
            if source_component == target_component:
                continue
            if target_component not in outgoing[source_component]:
                outgoing[source_component].add(target_component)
                incoming[target_component] += 1

    remaining = set(range(len(components)))
    waves: list[tuple[str, ...]] = []
    while remaining:
        ready_components = tuple(
            sorted(
                (index for index in remaining if incoming[index] == 0),
                key=lambda index: components[index],
            )
        )
        if not ready_components:
            raise RuntimeError("participant SCC condensation unexpectedly contains a cycle")
        wave = tuple(
            role
            for index in ready_components
            for role in components[index]
        )
        waves.append(wave)
        for index in ready_components:
            remaining.remove(index)
            for target in outgoing[index]:
                incoming[target] -= 1
    return tuple(waves)


__all__ = [
    "PARTICIPANT_COMMUNICATION_RELATION",
    "PARTICIPANT_DEPENDENCY_RELATION",
    "PARTICIPANT_FEEDBACK_RELATION",
    "PARTICIPANT_GRAPH_TRAIT",
    "PARTICIPANT_SHARED_STATE_RELATION",
    "PARTICIPANT_SUPERVISION_RELATION",
    "PARTICIPANT_VERTEX_TRAIT",
    "participant_communication",
    "participant_coordination_components",
    "participant_dependency",
    "participant_graph",
    "participant_relation",
    "participant_roles",
    "participant_waves",
    "validate_participant_graph",
]
