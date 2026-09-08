from __future__ import annotations

import json
from pathlib import Path

from noetrium.contracts.discovery import (
    find_downstream_symbol_schema,
    load_downstream_interface_schema,
)


ROOT = Path(__file__).resolve().parents[1]


def test_generated_interface_schema_covers_every_public_export() -> None:
    document = load_downstream_interface_schema()
    registry = json.loads(
        (ROOT / "noetrium_platform/foundation/governance/system_registry/catalog.json").read_text(
            encoding="utf-8"
        )
    )
    assert {row["system_key"] for row in document["systems"]} == set(registry)
    assert document["interface_schema"]["schema_id"] == "noetrium.interface-schema"

    for system in document["systems"]:
        for api in system["api_modules"]:
            assert set(api["symbols"]) == {
                schema["name"] for schema in api["symbol_schemas"]
            }
            assert all(
                schema["schema_id"] == "noetrium.interface-schema"
                for schema in api["symbol_schemas"]
            )


def test_generated_interface_schema_exposes_protocol_methods_and_reexports() -> None:
    module = "noetrium_platform.capabilities.environment.minecraft.api.ports"
    schema = find_downstream_symbol_schema(
        "environment/minecraft",
        module,
        "MinecraftBridgePort",
    )
    assert schema["kind"] == "class"
    assert any(method["name"] == "command" for method in schema["methods"])
    assert any(method["name"] == "reconcile_action" for method in schema["methods"])

    reexport = find_downstream_symbol_schema(
        "environment/minecraft",
        "noetrium_platform.capabilities.environment.minecraft.api",
        "MinecraftBridgePort",
    )
    assert reexport["kind"] == "reexport"
    assert reexport["origin_name"] == "MinecraftBridgePort"
