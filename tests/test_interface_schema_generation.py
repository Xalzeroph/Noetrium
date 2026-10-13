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
        (ROOT / "noetrium_platform/foundation/governance/system_registry/catalog.json")
        .read_text(encoding="utf-8")
    )
    assert {row["system_key"] for row in document["systems"]} == set(registry)
    assert len(document["interface_digest"]) == 64
    assert document["interface_schema"]["schema_id"] == "noetrium.interface-schema"

    public = document["public_api"]
    assert public["module"] == "noetrium"
    assert tuple(public["symbols"]) == ("NoetriumUnit", "run")
    assert tuple(document["authoring_inspection"]["public_roots"]) == (
        "NoetriumUnit",
        "run",
    )
    assert set(document["reachable_types"]) == {"unit", "run"}
    assert set(document["system_capability_projection"]) == set(registry)

    for system in document["systems"]:
        for api in system["api_modules"]:
            assert set(api["symbols"]) == {
                schema["name"] for schema in api["symbol_schemas"]
            }


def test_generated_interface_schema_exposes_one_recursive_unit_algebra() -> None:
    unit = find_downstream_symbol_schema(
        "research",
        "noetrium",
        "NoetriumUnit",
    )
    assert unit["kind"] == "reexport"

    run = find_downstream_symbol_schema(
        "research",
        "noetrium",
        "run",
    )
    assert run["kind"] == "reexport"

    document = load_downstream_interface_schema()
    reachable = document["reachable_types"]
    unit_schema = reachable["unit"]
    run_schema = reachable["run"]

    assert unit_schema["name"] == "NoetriumUnit"
    methods = {row["name"] for row in unit_schema["methods"]}
    assert {
        "make_structure",
        "make_symbol",
        "make_relation",
        "role",
        "units",
        "refs",
        "walk",
        "unit_at_path",
        "paths_with_schema",
        "units_with_schema",
    } <= methods
    assert run_schema["name"] == "run"

    inspection = document["authoring_inspection"]
    assert inspection["static_truth"] == "immutable recursive NoetriumUnit"
    assert inspection["semantic_value"] == "NoetriumUnit"
    assert inspection["public_roots"] == ["NoetriumUnit", "run"]
    assert "never parallel carrier classes" in inspection["semantic_model"]
    assert "mutable control truth never lives on Unit" in inspection["runtime_model"]


def test_interface_schema_validation_rejects_tampered_digest() -> None:
    document = json.loads(
        (ROOT / "noetrium/contracts/interface_schema.json").read_text(
            encoding="utf-8"
        )
    )
    document["interface_digest"] = "0" * 64
    with pytest.raises(DownstreamCatalogIntegrityError, match="interface schema digest"):
        validate_downstream_interface_schema(document)
