from __future__ import annotations

import importlib
import importlib.util
import sys
import json
from pathlib import Path

import pytest

from noetrium.contracts.discovery import (
    DownstreamCatalogIntegrityError,
    load_downstream_capability_catalog,
    validate_downstream_capability_catalog,
)


ROOT = Path(__file__).resolve().parents[1]


def test_generated_catalog_covers_exact_registry_as_internal_metadata() -> None:
    registry = json.loads(
        (ROOT / "noetrium_platform/foundation/governance/system_registry/catalog.json")
        .read_text(encoding="utf-8")
    )
    catalog = load_downstream_capability_catalog()
    assert {row.system_key for row in catalog.systems} == set(registry)
    assert catalog.entrypoint == "noetrium.api"
    assert catalog.ambiguous_symbol_sources == {}
    public = tuple(
        surface for surface in catalog.systems
        if surface.downstream_surface == "public"
    )
    assert len(public) == 1
    assert public[0].system_key == "research_os"
    modules = {api.module: api for api in public[0].api_modules}
    assert set(modules) == {"noetrium_platform.product.api"}
    assert set(modules["noetrium_platform.product.api"].symbols) == {
        "ResearchPortfolioBuilder",
        "ResearchPortfolio",
    }
    assert catalog.direct_symbol_sources == {
        "ResearchPortfolio": "noetrium_platform.product.api",
        "ResearchPortfolioBuilder": "noetrium_platform.product.api",
    }
    assert all(
        surface.api_modules == ()
        for surface in catalog.systems
        if surface.system_key != "research_os"
    )
    assert (
        ROOT / "docs/architecture/VNEXT_SYSTEM_CATALOG.json"
    ).read_bytes() == (
        ROOT / "noetrium_platform/foundation/governance/system_registry/catalog.json"
    ).read_bytes()


def test_generated_system_facades_are_metadata_only() -> None:
    catalog = load_downstream_capability_catalog()
    for surface in catalog.systems:
        assert surface.facade_module is not None
        module = importlib.import_module(surface.facade_module)
        assert module.SYSTEM_KEY == surface.system_key
        if surface.system_key == "research_os":
            expected = tuple(
                dict.fromkeys(
                    symbol
                    for api_module in surface.api_modules
                    for symbol in api_module.symbols
                )
            )
            assert tuple(module.__all__) == expected
        else:
            assert module.__all__ == ()


def test_noetrium_api_is_exact_product_surface() -> None:
    from noetrium import api
    from noetrium_platform.product import api as product_api

    assert tuple(product_api.__all__) == (
        "ResearchPortfolioBuilder",
        "ResearchPortfolio",
    )
    assert tuple(api.__all__) == (
        "ResearchPortfolioBuilder",
        "ResearchPortfolio",
        "ResearchOS",
        "open_project",
    )
    for name in product_api.__all__:
        assert getattr(api, name) is getattr(product_api, name)

    for retired in (
        "research_os",
        "research_authoring",
        "execution_authoring",
        "research_requirements",
        "ResearchProgramBuilder",
        "ResearchMethodBuilder",
        "MethodProgramBuilder",
        "WorkloadTrialProvider",
        "ResearchExecutionTarget",
    ):
        assert not hasattr(api, retired)


def test_product_surface_contains_research_os_authoring_and_control() -> None:
    from noetrium import api

    assert set(api.__all__) == {
        "ResearchPortfolioBuilder",
        "ResearchPortfolio",
        "ResearchOS",
        "open_project",
    }
    portfolio = api.ResearchPortfolioBuilder("fixture")
    program = portfolio.program("paper")
    assert type(program).__name__ == "ResearchProgramBuilder"
    assert not hasattr(api, type(program).__name__)


def test_catalog_keeps_capability_topology_without_exposing_system_symbols() -> None:
    catalog = load_downstream_capability_catalog()
    assert len(catalog.catalog_digest) == 64
    assert all(len(surface.interface_digest) == 64 for surface in catalog.systems)

    capability = next(
        capability
        for surface in catalog.systems
        for capability in surface.provides
    )
    providers = catalog.providers(capability)
    assert providers
    assert all(capability in surface.provides for surface in providers)


def test_catalog_validation_rejects_stale_topology() -> None:
    document = json.loads(
        (ROOT / "noetrium/contracts/downstream_capability_catalog.json").read_text(
            encoding="utf-8"
        )
    )
    document["topology_digest"] = "0" * 64
    with pytest.raises(DownstreamCatalogIntegrityError, match="canonical system registry"):
        validate_downstream_capability_catalog(document)


def test_catalog_validation_rejects_tampered_document_digest() -> None:
    document = json.loads(
        (ROOT / "noetrium/contracts/downstream_capability_catalog.json").read_text(
            encoding="utf-8"
        )
    )
    document["catalog_digest"] = "0" * 64
    with pytest.raises(DownstreamCatalogIntegrityError, match="catalog digest"):
        validate_downstream_capability_catalog(document)


def test_generator_readme_drift_fails_closed(tmp_path, monkeypatch) -> None:
    script = ROOT / "scripts/generate_downstream_contracts.py"
    spec = importlib.util.spec_from_file_location("_noetrium_generate_contracts_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    registry = tmp_path / "noetrium_platform/foundation/governance/system_registry/catalog.json"
    registry.parent.mkdir(parents=True)
    registry.write_text("{}\n", encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text(
        module.README_BLOCK_START + "\nstale\n" + module.README_BLOCK_END + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "build_surfaces", lambda _root: ())
    monkeypatch.setattr(module, "render_init", lambda _surfaces: "")
    monkeypatch.setattr(module, "render_catalog", lambda _root, _surfaces: b"{}\n")
    monkeypatch.setattr(module, "render_markdown", lambda _root, _surfaces: b"")
    monkeypatch.setattr(module, "render_root_contract_init", lambda _root: "")
    monkeypatch.setattr(
        module,
        "render_readme_interface_block",
        lambda _root, _surfaces: (
            module.README_BLOCK_START
            + "\ncurrent\n"
            + module.README_BLOCK_END
        ),
    )
    monkeypatch.setattr(module, "_readme_paths", lambda _root: (readme,))
    monkeypatch.setattr(module, "_write_or_check", lambda *_args, **_kwargs: True)
    assert module.generate(tmp_path, check=True) == 1


def test_generator_rejects_system_facade_symbol_collision() -> None:
    script = ROOT / "scripts/generate_downstream_contracts.py"
    spec = importlib.util.spec_from_file_location(
        "_noetrium_generate_contracts_collision_test",
        script,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    surface = module.SystemSurface(
        system_key="fixture",
        package_prefix="fixture",
        authority=None,
        canonical_authority=None,
        node_kind="facet",
        owns="fixture",
        must_not_own="none",
        requires=(),
        provides=(),
        downstream_surface="public",
        api_modules=(
            module.ApiModuleSurface("fixture.api.left", "left.py", ("Value",)),
            module.ApiModuleSurface("fixture.api.right", "right.py", ("Value",)),
        ),
        facade_module="noetrium.contracts.systems.fixture",
    )
    with pytest.raises(
        RuntimeError,
        match="symbol collision requires one canonical API owner",
    ):
        module.render_facade(surface)
