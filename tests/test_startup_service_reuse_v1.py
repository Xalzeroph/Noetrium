from __future__ import annotations

from noetrium_platform.capabilities.environment.category.composition import (
    default_environment_category_catalog,
)
from noetrium_platform.composition.managed_research_services import (
    build_managed_research_services,
)
from noetrium_platform.composition.platform_meta import build_platform_meta
from noetrium_platform.infrastructure.resources.authority import (
    UniversalResourceAuthority,
)


def test_default_environment_catalog_is_a_process_immutable_singleton():
    first = default_environment_category_catalog()
    second = default_environment_category_catalog()
    assert first is second
    assert first.catalog_digest == second.catalog_digest


def test_runtime_borrows_one_platform_result_query_and_catalog(tmp_path):
    root = tmp_path / "platform"
    authority = UniversalResourceAuthority(tmp_path / "resources.sqlite")
    meta = build_platform_meta(root, resource_authority=authority)
    first = build_managed_research_services(tmp_path / "first", meta=meta)
    second = build_managed_research_services(tmp_path / "second", meta=meta)

    assert first.research_results is meta.research_results
    assert second.research_results is meta.research_results
    assert first.environment_categories is second.environment_categories
    assert first.environment_categories is default_environment_category_catalog()


def test_platform_bootstrap_keeps_portfolio_and_excludes_scope_tables(tmp_path):
    import sqlite3

    authority = UniversalResourceAuthority(tmp_path / "resources.sqlite")
    root = tmp_path / "platform"
    meta = build_platform_meta(root, resource_authority=authority)
    assert meta.portfolio is not None
    database = root / "platform-meta.sqlite"
    assert database.is_file()
    with sqlite3.connect(database) as conn:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert "scopes" not in tables
    assert "scope_meta" not in tables
