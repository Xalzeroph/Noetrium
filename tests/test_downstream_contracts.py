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


def test_generated_facades_are_importable() -> None:
    catalog = load_downstream_capability_catalog()
    for surface in catalog.systems:
        if surface.facade_module is None:
            continue
        module = importlib.import_module(surface.facade_module)
        assert tuple(module.__all__)
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
