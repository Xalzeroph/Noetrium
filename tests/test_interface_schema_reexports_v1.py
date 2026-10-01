from __future__ import annotations

from noetrium.contracts.discovery import (
    find_downstream_symbol_schema,
    load_downstream_interface_schema,
)


def _resolved(row: dict[str, object]) -> dict[str, object]:
    current = row
    seen = 0
    while current.get("kind") == "reexport":
        nested = current.get("resolved_schema")
        assert isinstance(nested, dict)
        current = nested
        seen += 1
        assert seen < 16
    return current


def test_top_level_schema_resolves_portfolio_root_shape() -> None:
    row = find_downstream_symbol_schema(
        "research_os",
        "noetrium.api",
        "ResearchPortfolioBuilder",
    )
    resolved = _resolved(row)
    assert resolved["kind"] == "class"
    methods = {method["name"] for method in resolved["methods"]}
    assert {"program", "depends", "freeze"} <= methods


def test_program_dsl_is_schema_reachable_but_not_public() -> None:
    document = load_downstream_interface_schema()
    program = document["reachable_dsl"]["program"]
    assert program["name"] == "ResearchProgramBuilder"
    methods = {method["name"] for method in program["methods"]}
    assert "method" in methods
    assert "study" in methods
    assert "experiment" in methods
    assert "freeze" in methods
    assert "method_program" not in methods
    assert "method_configurer" not in methods
    assert "ResearchProgramBuilder" not in document["public_api"]["symbols"]


def test_method_and_memory_are_nested_schema_only_dsl() -> None:
    document = load_downstream_interface_schema()
    method = document["reachable_dsl"]["method"]
    memory = document["reachable_dsl"]["memory"]
    assert method["name"] == "ResearchMethodBuilder"
    assert memory["name"] == "ResearchComponentBuilder"
    assert "ResearchMethodBuilder" not in document["public_api"]["symbols"]
    assert "ResearchComponentBuilder" not in document["public_api"]["symbols"]
    assert "memory" in {row["name"] for row in method["methods"]}


def test_top_level_schema_describes_only_high_level_runtime_binding() -> None:
    inspection = load_downstream_interface_schema()["authoring_inspection"]
    assert inspection["entrypoint"] == "noetrium.api"
    assert inspection["authoring_root"] == "ResearchPortfolioBuilder"
    assert inspection["runtime_root"] == "ResearchOS"
    assert inspection["project_opener"] == "open_project"
    assert "provider selection" in inspection["boundary"]
