from __future__ import annotations

import json
from pathlib import Path

import pytest

from noetrium.contracts.discovery import (
    DownstreamCatalogIntegrityError,
    find_downstream_symbol_schema,
    load_downstream_interface_schema,
    validate_downstream_interface_schema,
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
    assert len(document["interface_digest"]) == 64
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


def test_generated_interface_schema_exposes_unified_product_reexports() -> None:
    module = "noetrium_platform.product.api"
    research_os = find_downstream_symbol_schema(
        "research_os",
        module,
        "ResearchOS",
    )
    assert research_os["kind"] == "reexport"
    assert research_os["origin_name"] == "ResearchOS"

    exact_cut = find_downstream_symbol_schema(
        "research_os",
        module,
        "BenchmarkCutRequirement",
    )
    assert exact_cut["kind"] == "reexport"
    assert exact_cut["origin_name"] == "BenchmarkCutRequirement"

    decorator = find_downstream_symbol_schema(
        "research_os",
        module,
        "requires_benchmark_cut",
    )
    assert decorator["kind"] == "reexport"
    assert decorator["origin_name"] == "requires_benchmark_cut"


def test_interface_schema_validation_rejects_tampered_digest() -> None:
    document = json.loads(
        (ROOT / "noetrium/contracts/interface_schema.json").read_text(
            encoding="utf-8"
        )
    )
    document["interface_digest"] = "0" * 64
    with pytest.raises(DownstreamCatalogIntegrityError, match="interface schema digest"):
        validate_downstream_interface_schema(document)
