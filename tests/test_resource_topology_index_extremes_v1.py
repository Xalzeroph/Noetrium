import pytest

from noetrium_platform.infrastructure.resources.api.topology import (
    resource_node,
    resource_topology,
)
from noetrium_platform.infrastructure.resources.api.topology_index import (
    ResourceTopologyIndex,
)


def test_many_same_kind_resources_preserve_parallel_frontier():
    graph = resource_topology(
        "x",
        resources=(
            resource_node(
                "compute",
                kind="compute",
                authority_key="resource:compute",
            ),
            *tuple(
                resource_node(
                    f"endpoint-{index}",
                    kind="network-endpoint",
                    authority_key=f"resource:endpoint:{index}",
                )
                for index in range(1000)
            ),
        ),
        requires=tuple(
            (f"endpoint-{index}", "compute") for index in range(1000)
        ),
    )
    topology_index = ResourceTopologyIndex(graph)
    assert topology_index.ready_frontier(frozenset()) == ("compute",)
    frontier = topology_index.ready_frontier(frozenset({"compute"}))
    assert len(frontier) == 1000
    assert frozenset(frontier) == frozenset(
        f"endpoint-{index}" for index in range(1000)
    )
    assert topology_index.dependency_closure(frontier) == topology_index.resource_ids


def test_reverse_closure_handles_deep_chain_without_effect_semantics():
    names = tuple(f"r{index}" for index in range(512))
    graph = resource_topology(
        "chain",
        resources=tuple(
            resource_node(
                name,
                kind="resource",
                authority_key=f"resource:{name}",
            )
            for name in names
        ),
        requires=tuple(
            (names[index], names[index - 1])
            for index in range(1, len(names))
        ),
    )
    topology_index = ResourceTopologyIndex(graph)
    assert topology_index.acquire_order == names
    assert topology_index.release_order == tuple(reversed(names))
    assert topology_index.dependency_closure((names[-1],)) == frozenset(names)
    assert topology_index.reverse_dependency_closure((names[0],)) == frozenset(names)


def test_duplicate_authority_keys_fail_closed():
    graph = resource_topology(
        "duplicate-authority",
        resources=(
            resource_node("a", kind="x", authority_key="same"),
            resource_node("b", kind="x", authority_key="same"),
        ),
    )
    with pytest.raises(ValueError, match="authority keys must be unique"):
        ResourceTopologyIndex(graph)
