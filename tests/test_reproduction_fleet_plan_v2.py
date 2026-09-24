from __future__ import annotations

from scripts.run_reproduction_fleet import build_plan


def _lane(plan: dict, package: str) -> dict:
    rows = [row for row in plan["lanes"] if row["package"] == package]
    assert len(rows) == 1
    return rows[0]


def test_fleet_plan_is_derived_only_from_current_research_os_compilers() -> None:
    plan = build_plan()
    assert plan["schema"] == "noetrium.reproduction-fleet-plan.v3"
    assert plan["protocol_bound_count"] >= 91
    assert plan["compile_failure_count"] == 0
    assert plan["research_os_compiled_count"] == plan["protocol_bound_count"]
    assert plan["graph_node_count"] == plan["protocol_bound_count"]
    assert len(plan["portfolio_digest"]) == 64
    assert len(plan["graph_digest"]) == 64
    assert len(plan["plan_digest"]) == 64
    for row in plan["lanes"]:
        assert row["state"] == "research_os_compiled"
        assert row["study_factory_count"] >= 1
        assert len(row["research_program_digest"]) == 64
        assert len(row["research_graph_semantic_digest"]) == 64
        assert row["research_graph_node_id"] == row["package"] + "::reproduction"


def test_fleet_plan_exposes_exact_vs_parameterized_study_bindings() -> None:
    plan = build_plan()
    react = _lane(plan, "react_alfworld")
    assert react["exact_study_factory_count"] >= 1
    assert react["unresolved_study_parameters"] == ()

    adapt = _lane(plan, "adaptagent_acl2025")
    assert "split_id" in adapt["unresolved_study_parameters"]

    frontier = _lane(plan, "astranav_memory_cvpr2026")
    assert "benchmark_split_id" in frontier["unresolved_study_parameters"]
    assert frontier["study_factory_count"] >= 1


def test_fleet_plan_keeps_parameterized_method_factories_explicit() -> None:
    plan = build_plan()
    toolformer = _lane(plan, "toolformer")
    assert toolformer["method_program_digest"] is None
    assert any(
        blocker.startswith("method_factory_requires_binding:")
        for blocker in toolformer["blockers"]
    )



def test_all_protocol_bound_reproductions_have_exact_execution_bindings() -> None:
    plan = build_plan()
    unresolved = tuple(
        (
            row["package"],
            tuple(row["unresolved_study_parameters"]),
            tuple(row["blockers"]),
        )
        for row in plan["lanes"]
        if row["unresolved_study_parameters"] or row["blockers"]
    )
    assert unresolved == ()
