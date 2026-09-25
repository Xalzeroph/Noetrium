from __future__ import annotations

import pytest

from noetrium_platform.foundation.portfolio.api import ProgramSpec, WorkspaceSpec
from noetrium_platform.foundation.portfolio.runtime import InMemoryPortfolioCatalog, PortfolioNotFound
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE, ScopeIdentity, ScopeKind
from noetrium_platform.foundation.scope.runtime import InMemoryScopeRegistry, ScopeRegistryConflict


def test_portfolio_does_not_publish_metadata_when_scope_link_conflicts() -> None:
    scopes = InMemoryScopeRegistry()
    portfolio = InMemoryPortfolioCatalog(scopes)
    portfolio.register_workspace(WorkspaceSpec("target", "Target"))
    portfolio.register_workspace(WorkspaceSpec("other", "Other"))

    program_scope = ScopeIdentity(ScopeKind.PROGRAM, "program")
    scopes.register(program_scope, ScopeIdentity(ScopeKind.WORKSPACE, "other"))

    with pytest.raises(ScopeRegistryConflict, match="parent already fixed"):
        portfolio.register_program(ProgramSpec("program", "target", "Program"))

    with pytest.raises(PortfolioNotFound):
        portfolio.program("program")
    assert scopes.parent(program_scope) == ScopeIdentity(ScopeKind.WORKSPACE, "other")


def test_portfolio_idempotent_registration_keeps_scope_and_metadata_aligned() -> None:
    scopes = InMemoryScopeRegistry()
    portfolio = InMemoryPortfolioCatalog(scopes)
    workspace = WorkspaceSpec("ws", "Workspace")
    portfolio.register_workspace(workspace)
    portfolio.register_workspace(workspace)
    assert portfolio.workspace("ws") == workspace
    assert scopes.parent(workspace.scope) == PLATFORM_SCOPE
