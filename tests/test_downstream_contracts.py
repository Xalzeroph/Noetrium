from __future__ import annotations

import importlib
import json
from pathlib import Path

from noetrium.contracts.discovery import load_downstream_capability_catalog


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
