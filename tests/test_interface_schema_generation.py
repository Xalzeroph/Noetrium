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
    assert public["module"] == "noetrium.api"
    assert tuple(public["symbols"]) == (
        "ResearchPortfolioBuilder",
        "ResearchPortfolio",
        "ResearchOS",
        "open_project",
    )
    assert tuple(document["authoring_inspection"]["public_roots"]) == tuple(public["symbols"])
    assert set(document["reachable_dsl"]) == {
        "program",
        "method",
        "memory",
        "runtime",
    }

    for system in document["systems"]:
        for api in system["api_modules"]:
            assert set(api["symbols"]) == {
                schema["name"] for schema in api["symbol_schemas"]
            }


def test_generated_interface_schema_exposes_hierarchical_product_reexports() -> None:
    portfolio = find_downstream_symbol_schema(
        "research_os",
        "noetrium.api",
        "ResearchPortfolioBuilder",
    )
    assert portfolio["kind"] == "reexport"

    document = load_downstream_interface_schema()
    program = document["reachable_dsl"]["program"]
    method = document["reachable_dsl"]["method"]
    memory = document["reachable_dsl"]["memory"]

    assert program["kind"] == "class"
    assert {
        "method",
        "benchmark",
        "dataset",
        "model",
        "environment",
        "study",
        "experiment",
        "ablation",
        "robustness",
        "analysis",
        "publication",
        "freeze",
    } <= {row["name"] for row in program["methods"]}
    assert {
        "agent",
        "memory",
        "capability",
        "route",
        "checkpoint",
        "interrupt",
        "build",
    } <= {row["name"] for row in method["methods"]}
    assert {
        "semantic",
        "custom",
        "build",
        "end",
    } <= {row["name"] for row in memory["methods"]}


def test_interface_schema_validation_rejects_tampered_digest() -> None:
    document = json.loads(
        (ROOT / "noetrium/contracts/interface_schema.json").read_text(
            encoding="utf-8"
        )
    )
    document["interface_digest"] = "0" * 64
    with pytest.raises(DownstreamCatalogIntegrityError, match="interface schema digest"):
        validate_downstream_interface_schema(document)
