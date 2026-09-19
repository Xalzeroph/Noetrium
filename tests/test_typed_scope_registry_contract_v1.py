from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE, ScopeIdentity, ScopeKind
from noetrium_platform.foundation.scope.providers import SQLiteScopeRegistry
from noetrium_platform.foundation.scope.runtime import InMemoryScopeRegistry, ScopeRegistryConflict


def _wrong_parent_case(registry) -> None:
    workspace = ScopeIdentity(ScopeKind.WORKSPACE, "ws")
    project = ScopeIdentity(ScopeKind.PROJECT, "project")
    registry.register(workspace, PLATFORM_SCOPE)
    with pytest.raises(ScopeRegistryConflict, match="requires program"):
        registry.register(project, workspace)
    assert not registry.contains(project)


def test_in_memory_scope_provider_enforces_scope_parent_contract() -> None:
    _wrong_parent_case(InMemoryScopeRegistry())


def test_sqlite_scope_provider_enforces_same_scope_parent_contract() -> None:
    with TemporaryDirectory() as directory:
        _wrong_parent_case(SQLiteScopeRegistry(Path(directory) / "scope.sqlite"))


def test_scope_providers_reject_alternate_platform_root_identity() -> None:
    alternate = ScopeIdentity(ScopeKind.PLATFORM, "alternate")
    providers = [InMemoryScopeRegistry()]
    with TemporaryDirectory() as directory:
        providers.append(SQLiteScopeRegistry(Path(directory) / "scope.sqlite"))
        for registry in providers:
            with pytest.raises(ScopeRegistryConflict, match="fixed root"):
                registry.register(alternate, None)
