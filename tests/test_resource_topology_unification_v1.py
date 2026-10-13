import pytest

from noetrium_platform.foundation.kernel.structure import endpoint_child_id, relation_id
from noetrium_platform.infrastructure.resources.api.topology import (
    RESOURCE_REQUIRES_RELATION,
    resource_acquire_order,
    resource_node,
    resource_release_order,
    resource_relation,
    resource_topology,
)
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.infrastructure.resources.api.topology import RESOURCE_NODE_TRAIT, RESOURCE_TOPOLOGY_TRAIT


def test_lifecycle_is_derived_from_primitive_resource_requirements() -> None:
    graph = resource_topology(
        "resources",
        resources=(resource_node("compute",kind="compute"), resource_node("endpoint",kind="endpoint"), resource_node("environment",kind="environment"), resource_node("container",kind="container")),
        requires=(("endpoint","compute"),("environment","endpoint"),("container","environment")),
    )
    assert resource_acquire_order(graph) == ("compute","endpoint","environment","container")
    assert resource_release_order(graph) == tuple(reversed(resource_acquire_order(graph)))
    assert {relation_id(r) for r in graph.relations} == {RESOURCE_REQUIRES_RELATION}
    # Graph truth is semantic, never traversal-oriented: dependent requires prerequisite.
    assert {(endpoint_child_id(r.units('source')[0]), endpoint_child_id(r.units('target')[0])) for r in graph.relations} == {
        ("endpoint", "compute"), ("environment", "endpoint"), ("container", "environment")
    }


def test_resource_requirement_cycle_fails_closed() -> None:
    a,b=resource_node("a",kind="test"),resource_node("b",kind="test")
    with pytest.raises(ValueError, match="cycle"):
        resource_topology("cycle", resources=(a,b), requires=(("a","b"),("b","a")))


def test_resource_request_refines_to_topology_with_witness() -> None:
    from noetrium_platform.infrastructure.resources.api.topology import resource_demand,resource_request
    from noetrium_platform.infrastructure.resources.api.refinement import RESOURCE_DEMAND_TO_TOPOLOGY_REWRITE
    from noetrium_platform.foundation.kernel.unit_rewrite import refine_deterministically
    request=resource_request('r',purpose='test',demands=(resource_demand('compute',kind='compute'),resource_demand('endpoint',kind='network-endpoint')),relations=(resource_relation('endpoint','compute',RESOURCE_REQUIRES_RELATION),))
    topology,witness=refine_deterministically(RESOURCE_DEMAND_TO_TOPOLOGY_REWRITE,request)
    assert resource_acquire_order(topology)==('compute','endpoint')
    assert witness.source_semantic_digest==request.semantic_digest
    assert witness.target_semantic_digest==topology.semantic_digest
