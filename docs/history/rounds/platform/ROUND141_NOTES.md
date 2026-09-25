# Round 141 — system-registry child index and BFS repair

Date: 2026-08-28

## Change

`InMemorySystemRegistry` now maintains an owner-local `_children` index when systems are registered. `children()` therefore reads the indexed child keys instead of scanning the complete registry on every query.

`descendants()` now uses `collections.deque.popleft()` for breadth-first traversal instead of `list.pop(0)`. Child keys remain sorted before expansion, so the externally visible deterministic breadth-first ordering is preserved.

## Boundary

The topology authority remains `governance/system_registry/catalog.json`. The new index is an in-memory derived acceleration structure, not a second topology authority and not durable state.

## Verification

`tests/test_vnext_system_tree.py` includes an explicit sorted-BFS regression for indexed children/descendants. The optimization must preserve the same descriptor identities and ordering as the previous implementation.
