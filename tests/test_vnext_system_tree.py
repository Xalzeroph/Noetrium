from noetrium_platform.foundation.governance.system_registry.api import (
    AuthorityDescriptor,
    SystemDescriptor,
    SystemIdentity,
    SystemLayer,
    SystemNodeKind,
)
from noetrium_platform.foundation.governance.system_registry.runtime.registry import (
    InMemorySystemRegistry,
    SystemRegistryConflict,
)


def node(key: tuple[str, ...], pkg: str) -> SystemDescriptor:
    identity = SystemIdentity(key[0], key[1:])
    if len(key) == 1:
        return SystemDescriptor(
            identity=identity,
            layer=SystemLayer.KERNEL,
            package_prefix=pkg,
            node_kind=SystemNodeKind.AUTHORITY,
            authorities=(AuthorityDescriptor(f"{key[0]}_authority"),),
            canonical_authority_key=identity.key,
        )
    return SystemDescriptor(
        identity=identity,
        layer=SystemLayer.INFRASTRUCTURE,
        package_prefix=pkg,
        node_kind=SystemNodeKind.FACET,
        canonical_authority_key=key[0],
    )


def test_recursive_system_tree_exposes_explicit_ownership() -> None:
    registry = InMemorySystemRegistry()
    registry.register(node(("kernel",), "noetrium_platform.foundation.kernel.kernel"))
    registry.register(node(("kernel", "identity"), "noetrium_platform.foundation.kernel.kernel.identity"))
    registry.register(node(("kernel", "errors"), "noetrium_platform.foundation.kernel.kernel.errors"))

    assert [x.identity.key for x in registry.children("kernel")] == ["kernel/errors", "kernel/identity"]
    assert [x.identity.key for x in registry.descendants("kernel")] == ["kernel/errors", "kernel/identity"]
    assert registry.ancestors("kernel/errors")[0].identity.key == "kernel"
    assert registry.owner_for_module("noetrium_platform.foundation.kernel.kernel.errors.descriptor").identity.key == "kernel/errors"


def test_system_child_requires_registered_parent() -> None:
    registry = InMemorySystemRegistry()
    try:
        registry.register(node(("kernel", "errors"), "noetrium_platform.infrastructure.reliability"))
    except Exception as exc:
        assert exc.__class__.__name__ == "SystemRegistryNotFound"
    else:
        raise AssertionError("system tree allowed an unregistered parent")


def test_descendants_preserve_sorted_breadth_first_topology_with_child_index() -> None:
    registry = InMemorySystemRegistry()
    registry.register(node(("kernel",), "noetrium_platform.foundation.kernel.kernel"))
    registry.register(node(("kernel", "zeta"), "noetrium_platform.foundation.kernel.kernel.zeta"))
    registry.register(node(("kernel", "alpha"), "noetrium_platform.foundation.kernel.kernel.alpha"))
    registry.register(node(("kernel", "alpha", "leaf"), "noetrium_platform.foundation.kernel.kernel.alpha.leaf"))

    assert [item.identity.key for item in registry.children("kernel")] == [
        "kernel/alpha",
        "kernel/zeta",
    ]
    assert [item.identity.key for item in registry.descendants("kernel")] == [
        "kernel/alpha",
        "kernel/zeta",
        "kernel/alpha/leaf",
    ]
