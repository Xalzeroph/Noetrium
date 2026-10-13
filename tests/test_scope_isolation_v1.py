from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE, ScopeKind, scope_key, scope_unit
from noetrium_platform.foundation.scope.runtime import InMemoryScopeIndex


def _register_many_children(index: InMemoryScopeIndex, *, count: int = 64):
    workspace = scope_unit(ScopeKind.WORKSPACE, "ws")
    index.register(workspace, PLATFORM_SCOPE)
    children = tuple(scope_unit(ScopeKind.PROGRAM, f"program-{value:03d}") for value in range(count))
    with ThreadPoolExecutor(max_workers=8) as pool:
        tuple(pool.map(lambda child: index.register(child, workspace), children))
    return workspace, children


def test_scope_index_is_thread_safe_for_concurrent_children() -> None:
    index = InMemoryScopeIndex()
    workspace, children = _register_many_children(index)
    assert index.children(workspace) == tuple(sorted(children, key=scope_key))
    assert all(index.parent(child) == workspace for child in children)


def test_scope_index_maintains_parent_local_projection() -> None:
    index = InMemoryScopeIndex()
    workspace, children = _register_many_children(index, count=96)
    assert set(index.children(workspace)) == set(children)
    assert all(index.contains(child) for child in children)
    assert len(index.links()) == len(children) + 1


def test_scope_index_is_disposable_and_rebuildable_from_units() -> None:
    first = InMemoryScopeIndex()
    workspace, children = _register_many_children(first, count=16)
    links = first.links()
    rebuilt = InMemoryScopeIndex()
    rebuilt.register(workspace, PLATFORM_SCOPE)
    for child in children:
        rebuilt.register(child, workspace)
    assert rebuilt.children(workspace) == first.children(workspace)
    assert tuple(link.unit_digest for link in rebuilt.links()) == tuple(link.unit_digest for link in links)
