from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from multiprocessing import get_context
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE, ScopeIdentity, ScopeKind
from noetrium_platform.foundation.scope.providers import SQLiteScopeRegistry
from noetrium_platform.foundation.scope.runtime import InMemoryScopeRegistry


def _register_many_children(registry, *, count: int = 64) -> tuple[ScopeIdentity, ...]:
    workspace = ScopeIdentity(ScopeKind.WORKSPACE, "ws")
    registry.register(workspace, PLATFORM_SCOPE)
    children = tuple(ScopeIdentity(ScopeKind.PROGRAM, f"program-{index:03d}") for index in range(count))
    with ThreadPoolExecutor(max_workers=8) as pool:
        tuple(pool.map(lambda child: registry.register(child, workspace), children))
    return children


def test_in_memory_scope_registry_is_thread_safe_for_concurrent_children() -> None:
    registry = InMemoryScopeRegistry()
    children = _register_many_children(registry)
    workspace = ScopeIdentity(ScopeKind.WORKSPACE, "ws")
    assert registry.children(workspace) == tuple(sorted(children, key=lambda item: item.key))


def test_sqlite_scope_registry_is_thread_safe_for_concurrent_children() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "scope.sqlite"
        registry = SQLiteScopeRegistry(path, timeout_seconds=5.0)
        children = _register_many_children(registry)
        workspace = ScopeIdentity(ScopeKind.WORKSPACE, "ws")
        assert registry.children(workspace) == tuple(sorted(children, key=lambda item: item.key))
        assert SQLiteScopeRegistry(path).children(workspace) == tuple(sorted(children, key=lambda item: item.key))


def _bootstrap_registry_process(path: str, barrier) -> None:
    barrier.wait(timeout=30)
    registry = SQLiteScopeRegistry(path, timeout_seconds=10.0)
    if not registry.contains(PLATFORM_SCOPE):
        raise AssertionError("platform root missing after concurrent bootstrap")


def test_in_memory_scope_registry_maintains_parent_local_child_index() -> None:
    registry = InMemoryScopeRegistry()
    children = _register_many_children(registry, count=96)
    workspace = ScopeIdentity(ScopeKind.WORKSPACE, "ws")
    assert registry._children[workspace] == set(children)
    assert all(child in registry._children for child in children)


def test_sqlite_scope_registry_parallel_first_open_is_idempotent() -> None:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "scope-bootstrap.sqlite"
        context = get_context("spawn")
        barrier = context.Barrier(8)
        processes = [
            context.Process(target=_bootstrap_registry_process, args=(str(path), barrier))
            for _ in range(8)
        ]
        try:
            for process in processes:
                process.start()
            for process in processes:
                process.join(45)
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(5)
        assert [process.exitcode for process in processes] == [0] * len(processes)
        with closing(sqlite3.connect(path)) as conn:
            versions = conn.execute(
                "SELECT value FROM scope_meta WHERE key='schema_version'"
            ).fetchall()
            roots = conn.execute(
                "SELECT COUNT(*) FROM scopes WHERE scope_key=?",
                (PLATFORM_SCOPE.key,),
            ).fetchone()[0]
        assert versions == [(str(SQLiteScopeRegistry.SCHEMA_VERSION),)]
        assert roots == 1
