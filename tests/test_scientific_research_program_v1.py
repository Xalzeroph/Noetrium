from __future__ import annotations

import json
from pathlib import Path

from scripts.validate_research_program import (
    SCHEMA,
    load_and_validate,
    validate_research_program,
)


def _document() -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "policy": {
            "external_repositories_are_runtime_dependencies": False,
            "platform_promotion_reasons": [
                "shared_by_multiple_methods",
                "cross_cutting_runtime_invariant",
                "required_for_reproducibility",
            ],
        },
        "benchmarks": [
            {
                "benchmark_id": "bench",
                "title": "Bench",
                "source_uri": "https://example.test/bench",
                "environment_kinds": ["software"],
            }
        ],
        "methods": [
            {
                "method_id": "method",
                "title": "Method",
                "year": 2026,
                "paper_uri": "https://example.test/paper",
                "reference_repositories": ["https://github.com/example/method"],
                "families": ["tool_use"],
                "reproduction_status": "queued",
                "priority": 1,
                "benchmark_ids": ["bench"],
                "platform_pressure": ["model/request"],
                "method_owned": ["scientific policy"],
                "platform_owned": ["model invocation"],
                "evidence_refs": [],
            }
        ],
        "platform_gaps": [
            {
                "gap_id": "gap",
                "status": "active",
                "promotion_reason": "cross_cutting_runtime_invariant",
                "trigger_method_ids": ["method"],
                "target_systems": ["model/request"],
                "problem": "A reusable runtime invariant is missing.",
            }
        ],
        "project_constraints": [
            {
                "project_id": "paper-a",
                "reason": "Keep an external method feature out of this paper.",
                "forbidden_method_features": [
                    {"method_id": "method", "features": ["external_feature"]}
                ],
            }
        ],
        "innovation_tracks": [
            {
                "innovation_id": "idea",
                "status": "idea",
                "parent_method_ids": ["method"],
                "downstream_project": "paper-a",
                "scientific_boundary": "The paper owns novelty; the platform owns generic runtime.",
                "blocked_by_innovation_ids": [],
            }
        ],
    }


def test_research_program_accepts_typed_cross_references() -> None:
    assert validate_research_program(_document(), {"model/request": {}}) == ()


def test_research_program_rejects_external_runtime_dependencies() -> None:
    document = _document()
    document["policy"]["external_repositories_are_runtime_dependencies"] = True
    findings = validate_research_program(document, {"model/request": {}})
    assert {row.code for row in findings} >= {"EXTERNAL_RUNTIME_DEPENDENCY_FORBIDDEN"}


def test_research_program_rejects_unknown_platform_authority() -> None:
    document = _document()
    document["methods"][0]["platform_pressure"] = ["model/not-real"]
    findings = validate_research_program(document, {"model/request": {}})
    assert any(row.code == "UNKNOWN_PLATFORM_SYSTEM" and row.detail == "model/not-real" for row in findings)


def test_research_program_rejects_matched_reproduction_without_evidence() -> None:
    document = _document()
    document["methods"][0]["reproduction_status"] = "matched"
    findings = validate_research_program(document, {"model/request": {}})
    assert any(row.code == "MATCHED_WITHOUT_EVIDENCE" for row in findings)


def test_research_program_rejects_dangling_method_and_benchmark_refs() -> None:
    document = _document()
    document["methods"][0]["benchmark_ids"] = ["missing-benchmark"]
    document["platform_gaps"][0]["trigger_method_ids"] = ["missing-method"]
    findings = validate_research_program(document, {"model/request": {}})
    codes = {row.code for row in findings}
    assert "UNKNOWN_BENCHMARK" in codes
    assert "UNKNOWN_METHOD" in codes


def test_repository_research_program_validates_against_registry(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1]
    target = tmp_path
    (target / "research/catalog").mkdir(parents=True)
    (target / "noetrium_platform/foundation/governance/system_registry").mkdir(parents=True)
    document = json.loads((source / "research/catalog/research_program.json").read_text(encoding="utf-8"))
    systems = {
        system
        for row in document["methods"]
        for system in row["platform_pressure"]
    } | {
        system
        for row in document["platform_gaps"]
        for system in row["target_systems"]
    }
    (target / "research/catalog/research_program.json").write_text(json.dumps(document), encoding="utf-8")
    (target / "noetrium_platform/foundation/governance/system_registry/catalog.json").write_text(
        json.dumps({system: {} for system in sorted(systems)}), encoding="utf-8"
    )
    loaded = load_and_validate(target)
    assert loaded["schema"] == SCHEMA


def test_research_program_rejects_unknown_method_in_project_constraint() -> None:
    document = _document()
    document["project_constraints"][0]["forbidden_method_features"][0]["method_id"] = "missing-method"
    findings = validate_research_program(document, {"model/request": {}})
    assert any(row.code == "UNKNOWN_METHOD" and row.detail == "missing-method" for row in findings)
