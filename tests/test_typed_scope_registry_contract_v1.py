from __future__ import annotations

import pytest

from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE, ScopeKind, scope_unit
from noetrium_platform.foundation.scope.runtime import InMemoryScopeIndex, ScopeIndexConflict, ScopeNotIndexed


def test_scope_index_enforces_exact_parent_kind() -> None:
    index = InMemoryScopeIndex()
    workspace = scope_unit(ScopeKind.WORKSPACE, "ws")
    project = scope_unit(ScopeKind.PROJECT, "project")
    index.register(workspace, PLATFORM_SCOPE)
    with pytest.raises(ScopeIndexConflict, match="requires program"):
        index.register(project, workspace)
    assert not index.contains(project)


def test_scope_index_rejects_alternate_platform_root_identity() -> None:
    index = InMemoryScopeIndex()
    alternate = scope_unit(ScopeKind.PLATFORM, "alternate")
    with pytest.raises(ScopeIndexConflict, match="fixed root"):
        index.register(alternate, None)


def test_scope_index_fail_closes_when_parent_is_not_indexed() -> None:
    index = InMemoryScopeIndex()
    missing_workspace = scope_unit(ScopeKind.WORKSPACE, "missing")
    program = scope_unit(ScopeKind.PROGRAM, "program")
    with pytest.raises(ScopeNotIndexed):
        index.register(program, missing_workspace)
    assert not index.contains(program)
