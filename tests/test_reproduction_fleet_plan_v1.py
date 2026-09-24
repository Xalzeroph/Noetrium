from __future__ import annotations

import importlib.util
from pathlib import Path


def _fleet_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_reproduction_fleet.py"
    spec = importlib.util.spec_from_file_location("noetrium_reproduction_fleet_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reproduction_fleet_is_complete_and_current_research_os_clean() -> None:
    payload = _fleet_module().build_plan()

    assert payload["schema"] == "noetrium.reproduction-fleet-plan.v9"
    assert payload["inventory_reproduction_count"] >= 100
    assert (
        payload["executable_reproduction_count"]
        + payload["non_executable_reproduction_count"]
        == payload["inventory_reproduction_count"]
    )
    assert payload["compile_failure_count"] == 0
    assert payload["research_os_compiled_count"] == payload[
        "executable_reproduction_count"
    ]
    assert payload["graph_node_count"] == payload["executable_reproduction_count"]
    assert len(payload["portfolio_digest"]) == 64
    assert len(payload["graph_digest"]) == 64
    assert len(payload["plan_digest"]) == 64
    assert payload["materialized_study_count"] >= payload["materialization_ready_count"]
    assert payload["study_authority_requirement_count"] == payload["materialized_study_count"]

    lane_packages = tuple(row["package"] for row in payload["lanes"])
    assert len(lane_packages) == len(set(lane_packages))
    assert len(lane_packages) == payload["executable_reproduction_count"]
    assert not set(lane_packages).intersection(payload["non_executable_packages"])


def test_non_executable_reproductions_are_explicit_inventory_entries() -> None:
    payload = _fleet_module().build_plan()

    packages = tuple(payload["non_executable_packages"])
    lifecycle = payload["non_executable_lifecycle"]
    assert packages
    assert set(packages) == set(lifecycle)
    assert set(lifecycle.values()).issubset(
        {"catalogued", "paper_only", "artifact_only"}
    )
