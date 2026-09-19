from __future__ import annotations

import json
from pathlib import Path

from scripts.sync_research_pressure import SUITE_SCHEMA, project


ROOT = Path(__file__).resolve().parents[1]


def _lane(status, package: str):
    return next(row for row in status["lanes"] if row["package"] == package)


def test_pressure_suite_supports_primary_plus_nested_executables() -> None:
    suite = json.loads(
        (ROOT / "research/catalog/pressure_suite.json").read_text(
            encoding="utf-8"
        )
    )
    assert suite["schema"] == SUITE_SCHEMA
    closure = suite["closure_contract"]
    assert closure["required_asset_kinds"] == ["fidelity", "study"]
    assert closure["executable_asset_kinds"] == [
        "method_program",
        "research_program",
    ]


def test_existing_method_program_pressure_lane_remains_ready() -> None:
    status = project()
    row = _lane(status, "adas_meta_agent_search")
    assert row["executable_asset_kinds"] == ["method_program"]
    assert row["ready"] is True
    assert row["gaps"] == []


def test_aflow_enters_pressure_as_optimization_research_program() -> None:
    status = project()
    row = _lane(status, "aflow")
    assert row["executable_asset_kinds"] == ["research_program"]
    assert row["benchmark_ids"] == ["humaneval"]
    assert row["ready"] is True
    assert row["gaps"] == []
    assert row["claim_ready"] is False
    assert "missing_execution_evidence" in row["claim_gaps"]


def test_voyager_primary_method_program_allows_nested_memory_programs() -> None:
    status = project()
    row = _lane(status, "voyager_minecraft")
    assert row["executable_asset_kinds"] == [
        "method_program",
        "research_program",
    ]
    assert row["primary_executable"] == {
        "kind": "method_program",
        "path": "research/reproductions/voyager_minecraft/program.py",
    }
    assert "ambiguous_executable_program" not in row["gaps"]
    assert row["ready"] is True
    assert row["gaps"] == []


def test_multimodal_memory_lanes_are_enforced_and_ready() -> None:
    status = project()
    for package in ("ma_lmm_memory", "moviechat_memory"):
        row = _lane(status, package)
        assert row["enforced"] is True
        assert row["ready"] is True
        assert row["gaps"] == []


def test_claim_readiness_is_separate_from_protocol_readiness() -> None:
    status = project()
    assert status["ready_count"] >= status["claim_ready_count"]
    assert status["enforced_ready_count"] >= status["enforced_claim_ready_count"]

    for package in (
        "flash_vstream_memory",
        "providellm_memory",
        "videollamb_memory",
        "deps_minecraft",
    ):
        row = _lane(status, package)
        assert row["enforced"] is True
        assert row["ready"] is True
        assert row["gaps"] == []
        assert row["claim_ready"] is False
        assert "lifecycle_not_matched_reproduction" in row["claim_gaps"]
        assert "missing_execution_evidence" in row["claim_gaps"]


def test_pressure_status_exposes_claim_evidence_counts() -> None:
    status = project()
    flash = _lane(status, "flash_vstream_memory")
    providellm = _lane(status, "providellm_memory")

    assert flash["reported_result_count"] == 3
    assert flash["reference_baseline_count"] == 1
    assert flash["evidence_ref_count"] == 0

    assert providellm["reported_result_count"] == 6
    assert providellm["reference_baseline_count"] == 2
    assert providellm["evidence_ref_count"] == 0
