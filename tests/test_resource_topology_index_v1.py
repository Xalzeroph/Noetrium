import pytest

from noetrium_platform.infrastructure.resources.api.topology import (
    resource_node,
    resource_topology,
)
from noetrium_platform.infrastructure.resources.api.topology_index import (
    ResourceTopologyIndex,
)


def _topology():
    return resource_topology(
        "tx",
        resources=(
            resource_node(
                "compute",
                kind="compute",
                authority_key="resource:compute",
            ),
            resource_node(
                "endpoint",
                kind="network-endpoint",
                authority_key="resource:endpoint",
            ),
            resource_node(
                "service",
                kind="service",
                authority_key="resource:service",
                realization=True,
            ),
        ),
        requires=(("endpoint", "compute"), ("service", "endpoint")),
    )


def test_dependency_and_release_order_are_graph_derived():
    topology_index = ResourceTopologyIndex(_topology())
    assert topology_index.acquire_order == ("compute", "endpoint", "service")
    assert topology_index.release_order == ("service", "endpoint", "compute")
    assert topology_index.prerequisites("compute") == ()
    assert topology_index.prerequisites("endpoint") == ("compute",)
    assert topology_index.prerequisites("service") == ("endpoint",)
    assert topology_index.dependents("compute") == ("endpoint",)
    assert topology_index.dependents("endpoint") == ("service",)
    assert topology_index.dependents("service") == ()


def test_resource_frontier_and_closures_are_pure_partial_order():
    topology_index = ResourceTopologyIndex(_topology())
    assert topology_index.ready_frontier(frozenset()) == ("compute",)
    assert topology_index.ready_frontier(frozenset({"compute"})) == ("endpoint",)
    assert topology_index.ready_frontier(
        frozenset({"compute", "endpoint"})
    ) == ("service",)
    assert topology_index.dependency_closure(("service",)) == frozenset(
        {"compute", "endpoint", "service"}
    )
    assert topology_index.reverse_dependency_closure(("compute",)) == frozenset(
        {"compute", "endpoint", "service"}
    )
    assert topology_index.acquire_subset({"compute", "service"}) == (
        "compute",
        "service",
    )
    assert topology_index.release_subset({"compute", "service"}) == (
        "service",
        "compute",
    )


def test_authority_and_realization_semantics_are_projected_from_nodes():
    topology_index = ResourceTopologyIndex(_topology())
    assert topology_index.authority_key("compute") == "resource:compute"
    assert topology_index.authority_key("endpoint") == "resource:endpoint"
    assert topology_index.authority_key("service") == "resource:service"
    assert not topology_index.requires_realization("compute")
    assert not topology_index.requires_realization("endpoint")
    assert topology_index.requires_realization("service")


def test_unknown_frontier_state_fails_closed():
    topology_index = ResourceTopologyIndex(_topology())
    with pytest.raises(ValueError, match="unknown resource"):
        topology_index.ready_frontier(frozenset({"foreign"}))
