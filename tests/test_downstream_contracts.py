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


def test_generated_catalog_covers_exact_registry() -> None:
    registry = json.loads(
        (ROOT / "noetrium_platform/foundation/governance/system_registry/catalog.json")
        .read_text(encoding="utf-8")
    )
    catalog = load_downstream_capability_catalog()
    assert {row.system_key for row in catalog.systems} == set(registry)
    assert catalog.topology_digest
    assert (
        ROOT / "docs/architecture/VNEXT_SYSTEM_CATALOG.json"
    ).read_bytes() == (
        ROOT / "noetrium_platform/foundation/governance/system_registry/catalog.json"
    ).read_bytes()


def test_generated_facades_are_importable() -> None:
    catalog = load_downstream_capability_catalog()
    for surface in catalog.systems:
        assert surface.facade_module is not None
        module = importlib.import_module(surface.facade_module)
        assert hasattr(module, "__all__")
        assert module.SYSTEM_KEY == surface.system_key
        for name in module.__all__:
            assert hasattr(module, name), (
                f"{surface.system_key}: missing generated export {name}"
            )


def test_persistent_session_contract_is_downstream_visible() -> None:
    module = importlib.import_module(
        "noetrium.contracts.systems.runtime__session"
    )
    assert hasattr(module, "PersistentSessionSpec")
    assert hasattr(module, "PersistentSessionRuntimePort")
    assert hasattr(module, "RuntimeControllerCommand")

    from noetrium.contracts import server, session

    assert session.PersistentSessionSpec is module.PersistentSessionSpec
    assert server.PersistentSessionSpec is module.PersistentSessionSpec
    assert "SYSTEM_FACADES" in __import__("noetrium.contracts", fromlist=["SYSTEM_FACADES"]).__all__


def test_reusable_memory_graph_is_downstream_visible() -> None:
    module = importlib.import_module(
        "noetrium.contracts.systems.components"
    )
    expected = {
        "MemoryGraphPort",
        "MemoryGraphSnapshot",
        "MemoryGraphOperation",
        "MemoryGraphTransaction",
        "VersionedMemoryGraph",
    }
    assert expected.issubset(set(module.__all__))
    graph = module.VersionedMemoryGraph(module.MemoryGraphSnapshot("g0", (), ()))
    assert graph.snapshot().generation == "g0"


def test_catalog_exposes_stable_document_and_surface_fingerprints() -> None:
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
    monkeypatch.setattr(module, "_CONVENIENCE_FACADES", {})
    monkeypatch.setattr(module, "_readme_paths", lambda _root: (readme,))
    monkeypatch.setattr(module, "_write_or_check", lambda *_args, **_kwargs: True)
    assert module.generate(tmp_path, check=True) == 1
