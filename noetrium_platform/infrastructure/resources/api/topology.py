from __future__ import annotations

from collections.abc import Mapping
from heapq import heapify, heappop, heappush

from noetrium_platform.foundation.governance.api import is_scope_unit, scope_to_data
from noetrium_platform.foundation.kernel.structure import (
    NoetriumUnit,
    endpoint_child_id,
    endpoint_unit,
    relation_id,
    relation_unit,
    structure_unit,
)
from noetrium_platform.foundation.kernel.kernel import JsonValue

RESOURCE_REQUEST_TRAIT = "resource.request"
RESOURCE_DEMAND_TRAIT = "resource.demand"

RESOURCE_REQUIRES_RELATION = "resource.requires"
RESOURCE_AFFINITY_RELATION = "resource.affinity"
RESOURCE_ANTI_AFFINITY_RELATION = "resource.anti-affinity"
RESOURCE_TOPOLOGY_TRAIT = "resource.topology"
RESOURCE_NODE_TRAIT = "resource.node"
RESOURCE_REALIZATION_TRAIT = "resource.realization"


def _text(value: str, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value.strip()


def resource_scope_payload(scope: NoetriumUnit | None) -> JsonValue:
    if scope is None:
        return None
    if not is_scope_unit(scope):
        raise TypeError("resource scope must be scope Unit or None")
    return scope_to_data(scope)


def resource_relation(
    source_id: str,
    target_id: str,
    relation_id: str,
    *,
    parameters: JsonValue = None,
) -> NoetriumUnit:
    return relation_unit(
        (endpoint_unit(_text(source_id, "resource relation source"), None),),
        (endpoint_unit(_text(target_id, "resource relation target"), None),),
        _text(relation_id, "resource relation id"),
        {} if parameters is None else parameters,
    )


def resource_demand(
    demand_id: str,
    *,
    kind: str,
    requirements: Mapping[str, JsonValue] | None = None,
    quantity: int = 1,
    preferences: Mapping[str, JsonValue] | None = None,
    realization: bool = False,
    children: tuple[NoetriumUnit, ...] = (),
    relations: tuple[NoetriumUnit, ...] = (),
) -> NoetriumUnit:
    if type(quantity) is not int or quantity < 1:
        raise ValueError("resource demand quantity must be a positive integer")
    if type(realization) is not bool:
        raise TypeError("resource demand realization must be boolean")
    return structure_unit(
        _text(demand_id, "resource demand id"),
        traits=(RESOURCE_DEMAND_TRAIT,),
        parameters={
            "kind": _text(kind, "resource demand kind"),
            "quantity": quantity,
            "requirements": {} if requirements is None else dict(requirements),
            "preferences": {} if preferences is None else dict(preferences),
            "realization": realization,
        },
        members=children,
        relations=relations,
    )


def resource_request(
    request_id: str,
    *,
    purpose: str,
    demands: tuple[NoetriumUnit, ...],
    metadata: Mapping[str, JsonValue] | None = None,
    relations: tuple[NoetriumUnit, ...] = (),
) -> NoetriumUnit:
    if type(demands) is not tuple or not demands:
        raise ValueError("resource request requires at least one demand")
    if any(type(row) is not NoetriumUnit or not row.has_trait(RESOURCE_DEMAND_TRAIT) for row in demands):
        raise TypeError("resource request children must be resource.demand NoetriumUnit values")
    return structure_unit(
        _text(request_id, "resource request id"),
        traits=(RESOURCE_REQUEST_TRAIT,),
        parameters={
            "purpose": _text(purpose, "resource request purpose"),
            "metadata": {} if metadata is None else dict(metadata),
        },
        members=demands,
        relations=relations,
    )


def resource_node(
    resource_id: str,
    *,
    kind: str,
    authority_key: str | None = None,
    realization: bool = False,
    parameters: Mapping[str, JsonValue] | None = None,
) -> NoetriumUnit:
    if type(realization) is not bool:
        raise TypeError("resource node realization must be boolean")
    resource_id = _text(resource_id, "resource node id")
    key = resource_id if authority_key is None else _text(authority_key, "resource authority key")
    traits = (RESOURCE_NODE_TRAIT, RESOURCE_REALIZATION_TRAIT) if realization else (RESOURCE_NODE_TRAIT,)
    return structure_unit(
        resource_id,
        traits=traits,
        parameters={
            "kind": _text(kind, "resource node kind"),
            "authority_key": key,
            **({} if parameters is None else dict(parameters)),
        },
    )




def resource_authority_key(resource: NoetriumUnit) -> str:
    if type(resource) is not NoetriumUnit or not resource.has_trait(RESOURCE_NODE_TRAIT):
        raise TypeError("resource authority key requires resource.node NoetriumUnit")
    parameters = resource.parameters
    if not isinstance(parameters, Mapping):
        raise TypeError("resource node parameters must be a mapping")
    return _text(parameters.get("authority_key"), "resource authority key")


def resource_requires_realization(resource: NoetriumUnit) -> bool:
    if type(resource) is not NoetriumUnit or not resource.has_trait(RESOURCE_NODE_TRAIT):
        raise TypeError("resource realization query requires resource.node NoetriumUnit")
    return resource.has_trait(RESOURCE_REALIZATION_TRAIT)

def resource_kind(resource: NoetriumUnit) -> str:
    if type(resource) is not NoetriumUnit or not resource.has_trait(RESOURCE_NODE_TRAIT):
        raise TypeError("resource kind requires resource.node NoetriumUnit")
    parameters = resource.parameters
    if not isinstance(parameters, Mapping):
        raise TypeError("resource node parameters must be a mapping")
    return _text(parameters.get("kind"), "resource node kind")


def resource_topology(
    topology_id: str,
    *,
    resources: tuple[NoetriumUnit, ...],
    requires: tuple[tuple[str, str], ...] = (),
) -> NoetriumUnit:
    """Canonical resource dependency topology.

    ``dependent requires prerequisite`` is the only stored lifecycle ordering
    fact. Acquire, release and recovery order are derived views and are never
    persisted as independent relations.
    """
    if type(resources) is not tuple or not resources:
        raise ValueError("resource topology requires at least one resource node")
    if any(type(row) is not NoetriumUnit or not row.has_trait(RESOURCE_NODE_TRAIT) for row in resources):
        raise TypeError("resource topology children must be resource.node graphs")
    ids={row.unit_id for row in resources}
    if len(ids) != len(resources):
        raise ValueError("resource topology node ids must be unique")
    relations=[]
    for dependent, prerequisite in requires:
        if dependent not in ids or prerequisite not in ids:
            raise ValueError("resource requirement endpoints must belong to topology")
        if dependent == prerequisite:
            raise ValueError("resource cannot require itself")
        # Store the semantic fact exactly as written: dependent -> prerequisite.
        # Traversal direction is an index concern and must never distort
        # canonical topology truth.
        relations.append(resource_relation(dependent, prerequisite, RESOURCE_REQUIRES_RELATION))
    topology = structure_unit(
        _text(topology_id, "resource topology id"),
        traits=(RESOURCE_TOPOLOGY_TRAIT,),
        members=resources,
        relations=tuple(relations),
    )
    resource_acquire_order(topology)  # fail-close on cycles at construction
    return topology


def resource_acquire_order(topology: NoetriumUnit) -> tuple[str, ...]:
    if type(topology) is not NoetriumUnit or not topology.has_trait(RESOURCE_TOPOLOGY_TRAIT):
        raise TypeError("resource acquire order requires resource.topology NoetriumUnit")
    if any(not child.has_trait(RESOURCE_NODE_TRAIT) for child in topology.members):
        raise TypeError("resource topology children must be resource.node Units")
    # `resource.requires` is stored dependent -> prerequisite.  Acquisition
    # needs the inverse execution order (prerequisites first), so derive that
    # view without persisting a second/precedes relation.
    child_ids = tuple(child.unit_id for child in topology.members)
    prerequisites: dict[str, set[str]] = {child_id: set() for child_id in child_ids}
    dependents: dict[str, set[str]] = {child_id: set() for child_id in child_ids}
    for relation in topology.relations:
        if relation_id(relation) != RESOURCE_REQUIRES_RELATION:
            continue
        for source in relation.units("source"):
            for target in relation.units("target"):
                prerequisites[endpoint_child_id(source)].add(endpoint_child_id(target))
                dependents[endpoint_child_id(target)].add(endpoint_child_id(source))
    ready = [child_id for child_id in child_ids if not prerequisites[child_id]]
    heapify(ready)
    order: list[str] = []
    scheduled: set[str] = set()
    while ready:
        current = heappop(ready)
        if current in scheduled:
            continue
        scheduled.add(current)
        order.append(current)
        for dependent in dependents[current]:
            prerequisites[dependent].discard(current)
            if not prerequisites[dependent] and dependent not in scheduled:
                heappush(ready, dependent)
    if len(order) != len(child_ids):
        raise ValueError("resource requirement topology contains a cycle")
    return tuple(order)


def resource_release_order(topology: NoetriumUnit) -> tuple[str, ...]:
    return tuple(reversed(resource_acquire_order(topology)))


def resource_request_digest(request: NoetriumUnit) -> str:
    if type(request) is not NoetriumUnit or not request.has_trait(RESOURCE_REQUEST_TRAIT):
        raise TypeError("resource request digest requires resource.request NoetriumUnit")
    return request.semantic_digest


__all__ = [
    "resource_acquire_order",
    "resource_release_order",
    "RESOURCE_REQUIRES_RELATION",
    "RESOURCE_TOPOLOGY_TRAIT",
    "RESOURCE_NODE_TRAIT",
    "RESOURCE_REALIZATION_TRAIT",
    "RESOURCE_AFFINITY_RELATION",
    "RESOURCE_ANTI_AFFINITY_RELATION",
    "RESOURCE_DEMAND_TRAIT",
    "RESOURCE_REQUEST_TRAIT",
    "resource_demand",
    "resource_node",
    "resource_kind",
    "resource_authority_key",
    "resource_requires_realization",
    "resource_topology",
    "resource_relation",
    "resource_request",
    "resource_request_digest",
    "resource_scope_payload",
]
