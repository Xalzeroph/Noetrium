from __future__ import annotations

import pytest

from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE, ScopeKind, scope_unit
from noetrium_platform.foundation.scope.runtime import InMemoryScopeIndex, ScopeIndexConflict, ScopeNotIndexed


def test_scope_projection_has_no_persistent_registry_authority() -> None:
    index = InMemoryScopeIndex()
    workspace = scope_unit(ScopeKind.WORKSPACE, "workspace")
    index.register(workspace, PLATFORM_SCOPE)
    assert index.ancestry(workspace) == (workspace, PLATFORM_SCOPE)
    fresh = InMemoryScopeIndex()
    assert not fresh.contains(workspace)


def test_scope_projection_missing_parent_is_atomic_fail_close() -> None:
    index = InMemoryScopeIndex()
    missing = scope_unit(ScopeKind.WORKSPACE, "missing")
    program = scope_unit(ScopeKind.PROGRAM, "program")
    with pytest.raises(ScopeNotIndexed):
        index.register(program, missing)
    assert not index.contains(program)


def test_scope_projection_parent_is_immutable_once_indexed() -> None:
    index = InMemoryScopeIndex()
    workspace = scope_unit(ScopeKind.WORKSPACE, "workspace")
    program = scope_unit(ScopeKind.PROGRAM, "program")
    index.register(workspace, PLATFORM_SCOPE)
    index.register(program, workspace)
    index.register(program, workspace)
    with pytest.raises(ScopeIndexConflict):
        index.register(program, PLATFORM_SCOPE)
