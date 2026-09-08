from noetrium_platform.foundation.governance.system_registry.api import system_catalog
from noetrium_platform.foundation.governance.system_registry.runtime import InMemorySystemRegistry



def _registry() -> InMemorySystemRegistry:
    registry = InMemorySystemRegistry()
    for descriptor in system_catalog():
        registry.register(descriptor)
    return registry


def test_complete_top_level_system_graph():
    roots = tuple(row for row in system_catalog() if row.identity.is_system)
    assert roots
    assert all(row.parent_key is None for row in roots)
    assert all(row.layer.value == row.identity.system_id for row in roots)


def test_systems_are_peers_not_platform_children():
    registry = _registry()
    assert registry.children("platform")
    assert all(child.identity.system_id == "platform" for child in registry.children("platform"))
    assert "scope" not in {child.identity.key for child in registry.children("platform")}


def test_recursive_children_are_derived_from_canonical_parent_links():
    registry = _registry()
    catalog = system_catalog()
    parent_keys = {row.parent_key for row in catalog if row.parent_key is not None}
    for parent_key in parent_keys:
        expected = tuple(
            sorted(row.identity.key for row in catalog if row.parent_key == parent_key)
        )
        observed = tuple(sorted(child.identity.key for child in registry.children(parent_key)))
        assert observed == expected
