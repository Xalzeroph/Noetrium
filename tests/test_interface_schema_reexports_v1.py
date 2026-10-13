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


def test_top_level_schema_resolves_recursive_noetrium_unit_shape() -> None:
    row = find_downstream_symbol_schema(
        "research", "noetrium", "NoetriumUnit"
    )
    resolved = _resolved(row)
    assert resolved["kind"] == "class"
    methods = {method["name"] for method in resolved["methods"]}
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
    assert "freeze" not in methods
    assert "programs" not in methods


def test_recursive_unit_is_the_only_public_semantic_carrier() -> None:
    document = load_downstream_interface_schema()
    reachable = document["reachable_types"]
    assert set(reachable) == {"unit", "run"}
    assert reachable["unit"]["name"] == "NoetriumUnit"
    assert reachable["run"]["name"] == "run"
    public = set(document["public_api"]["symbols"])
    assert public == {"NoetriumUnit", "run"}
    for retired in (
    ):
        assert retired not in public


def test_method_experiment_memory_and_graph_are_schemas_not_parallel_carriers() -> None:
    inspection = load_downstream_interface_schema()["authoring_inspection"]
    assert inspection["semantic_value"] == "NoetriumUnit"
    assert "schemas and projections" in inspection["semantic_model"]
    assert "never parallel carrier classes" in inspection["semantic_model"]
    assert "schemas, roles, attributes" in inspection["recursive_algebra"]


def test_top_level_schema_describes_static_and_dynamic_truth_boundary() -> None:
    inspection = load_downstream_interface_schema()["authoring_inspection"]
    assert inspection["entrypoint"] == "noetrium"
    assert inspection["public_roots"] == ["NoetriumUnit", "run"]
    assert inspection["execution_operation"] == "run"
    assert inspection["static_truth"] == "immutable recursive NoetriumUnit"
    assert "mutable control truth never lives on Unit" in inspection["runtime_model"]
    assert "Resources, deployment, Docker" in inspection["boundary"]
