from __future__ import annotations

from contextlib import closing
from pathlib import Path
import os
import sqlite3
from tempfile import TemporaryDirectory

import pytest

from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE, ScopeIdentity, ScopeKind
from noetrium_platform.foundation.scope.providers import SQLiteScopeRegistry
from noetrium_platform.foundation.scope.runtime import ScopeNotRegistered


def test_scope_sqlite_reopens_with_parent_lookup_index() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "scope.sqlite"
        registry = SQLiteScopeRegistry(path)
        workspace = ScopeIdentity(ScopeKind.WORKSPACE, "ws")
        registry.register(workspace, PLATFORM_SCOPE)

        reopened = SQLiteScopeRegistry(path)
        assert reopened.ancestry(workspace) == (workspace, PLATFORM_SCOPE)
        with closing(sqlite3.connect(path)) as conn:
            indexes = {row[1] for row in conn.execute("PRAGMA index_list('scopes')")}
            plan = tuple(
                row[3]
                for row in conn.execute(
                    "EXPLAIN QUERY PLAN SELECT kind,scope_id FROM scopes WHERE parent_key=?",
                    (PLATFORM_SCOPE.key,),
                )
            )
        assert SQLiteScopeRegistry.PARENT_INDEX in indexes
        assert any(SQLiteScopeRegistry.PARENT_INDEX in detail for detail in plan)


def test_scope_sqlite_relative_path_stays_bound_to_construction_directory() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        construction_dir = root / "construction"
        later_dir = root / "later"
        construction_dir.mkdir()
        later_dir.mkdir()
        previous_cwd = Path.cwd()
        try:
            os.chdir(construction_dir)
            registry = SQLiteScopeRegistry("scope.sqlite")
            workspace = ScopeIdentity(ScopeKind.WORKSPACE, "cwd-stable")
            registry.register(workspace, PLATFORM_SCOPE)
            expected_path = construction_dir / "scope.sqlite"
            assert registry.path == expected_path

            os.chdir(later_dir)
            assert registry.contains(workspace)
            assert registry.ancestry(workspace) == (workspace, PLATFORM_SCOPE)
            assert not (later_dir / "scope.sqlite").exists()
        finally:
            os.chdir(previous_cwd)


def test_scope_sqlite_failed_registration_rolls_back_completely() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "scope.sqlite"
        registry = SQLiteScopeRegistry(path)
        missing = ScopeIdentity(ScopeKind.WORKSPACE, "missing")
        program = ScopeIdentity(ScopeKind.PROGRAM, "program")
        with pytest.raises(ScopeNotRegistered):
            registry.register(program, missing)
        assert not SQLiteScopeRegistry(path).contains(program)


def test_scope_sqlite_rejects_corrupt_schema_version() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "scope.sqlite"
        SQLiteScopeRegistry(path)
        with closing(sqlite3.connect(path)) as conn:
            conn.execute("UPDATE scope_meta SET value='not-an-integer' WHERE key='schema_version'")
            conn.commit()
        with pytest.raises(RuntimeError, match="invalid .* schema version"):
            SQLiteScopeRegistry(path)
