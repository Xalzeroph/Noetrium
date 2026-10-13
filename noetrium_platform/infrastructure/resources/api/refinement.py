"""Canonical refinement from declarative resource demand to resource topology."""
from __future__ import annotations
from collections.abc import Mapping
from noetrium_platform.foundation.kernel.structure import NoetriumUnit, endpoint_child_id, relation_id
from noetrium_platform.foundation.kernel.unit_rewrite import deterministic_rewrite_identity
from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_digest
from .topology import RESOURCE_DEMAND_TRAIT, RESOURCE_REQUEST_TRAIT, RESOURCE_REQUIRES_RELATION, RESOURCE_TOPOLOGY_TRAIT, resource_node, resource_topology

class ResourceDemandToTopologyRewrite:
    rule_id="resource-demand-to-topology"
    source_traits=frozenset((RESOURCE_REQUEST_TRAIT,))
    target_traits=frozenset((RESOURCE_TOPOLOGY_TRAIT,))
    @property
    def identity_digest(self)->str:
        return deterministic_rewrite_identity(self.rule_id,self.source_traits,self.target_traits,{"version":1})
    def rewrite_one(self, graph:NoetriumUnit, *, context:Mapping[str,JsonValue])->NoetriumUnit:
        if context: raise ValueError("resource demand refinement accepts no contextual state")
        demands={child.unit_id:child for child in graph.members}
        if not demands or any(not child.has_trait(RESOURCE_DEMAND_TRAIT) for child in demands.values()): raise ValueError("resource request contains non-demand children")
        nodes=[]
        for demand_id,demand in demands.items():
            params=demand.parameters
            if not isinstance(params,Mapping): raise TypeError("resource demand parameters must be a mapping")
            kind=params.get("kind")
            if type(kind) is not str or not kind.strip(): raise ValueError("resource demand kind is required")
            nodes.append(resource_node(
                demand_id,
                kind=kind,
                authority_key="resource:" + canonical_digest({
                    "request": graph.semantic_digest,
                    "demand": demand_id,
                }),
                realization=bool(params.get("realization", False)),
                parameters={
                    "quantity":params.get("quantity",1),
                    "requirements":params.get("requirements",{}),
                    "preferences":params.get("preferences",{}),
                },
            ))
        requires=[]
        for relation in graph.relations:
            if relation_id(relation) != RESOURCE_REQUIRES_RELATION: continue
            for source in relation.units("source"):
                for target in relation.units("target"): requires.append((endpoint_child_id(source),endpoint_child_id(target)))
        return resource_topology(graph.unit_id+":topology",resources=tuple(nodes),requires=tuple(requires))

RESOURCE_DEMAND_TO_TOPOLOGY_REWRITE=ResourceDemandToTopologyRewrite()
__all__=["ResourceDemandToTopologyRewrite","RESOURCE_DEMAND_TO_TOPOLOGY_REWRITE"]
