from __future__ import annotations

from scripts.run_reproduction_fleet import build_plan


def _lane(plan: dict, package: str) -> dict:
    rows = [row for row in plan["lanes"] if row["package"] == package]
    assert len(rows) == 1
    return rows[0]


def test_fleet_plan_is_derived_only_from_current_research_os_compilers() -> None:
    plan = build_plan()
    assert plan["schema"] == "noetrium.reproduction-fleet-plan.v7"
    assert plan["compile_failure_count"] == 0
    assert plan["research_os_compiled_count"] == plan["executable_reproduction_count"]
    assert (
        plan["execution_ready_count"]
        + plan["benchmark_binding_required_count"]
        + plan["closure_binding_required_count"]
        == plan["executable_reproduction_count"]
    )
    assert plan["graph_node_count"] == plan["executable_reproduction_count"]
    assert len(plan["portfolio_digest"]) == 64
    assert len(plan["graph_digest"]) == 64
    assert len(plan["plan_digest"]) == 64
    for row in plan["lanes"]:
        assert row["state"] in {
            "execution_ready",
            "benchmark_binding_required",
            "closure_binding_required",
        }
        assert row["study_factory_count"] >= 1
        assert len(row["research_program_digest"]) == 64
        assert len(row["research_graph_semantic_digest"]) == 64
        assert row["research_graph_node_id"] == row["package"] + "::reproduction"
        assert row["blockers"] == ()


def test_fleet_plan_separates_benchmark_axis_from_typed_non_benchmark_closure() -> None:
    plan = build_plan()

    react = _lane(plan, "react_alfworld")
    assert react["state"] == "execution_ready"
    assert react["execution_requirement_parameters"] == ()
    assert react["execution_requirement_kinds"] == ()
    assert react["benchmark_split_axis_consumers"] == ()

    adapt = _lane(plan, "adaptagent_acl2025")
    assert adapt["state"] == "benchmark_binding_required"
    assert adapt["execution_requirement_parameters"] == ()
    assert adapt["execution_requirement_kinds"] == ()
    assert adapt["benchmark_split_axis_consumers"] == (
        "study:build_adaptagent_study",
    )

    frontier = _lane(plan, "astranav_memory_cvpr2026")
    assert frontier["state"] == "benchmark_binding_required"
    assert frontier["execution_requirement_parameters"] == ()
    assert frontier["execution_requirement_kinds"] == ()
    assert frontier["benchmark_split_axis_consumers"] == ("study:build_study",)
    assert frontier["study_factory_count"] >= 1

    storm = _lane(plan, "storm_wiki")
    assert storm["state"] == "closure_binding_required"
    assert storm["execution_requirement_parameters"] == ("search_capability_id",)
    assert storm["execution_requirement_kinds"] == ("capability_id",)
    assert storm["benchmark_split_axis_consumers"] == (
        "study:build_storm_freshwiki_study",
    )


def test_fleet_plan_materializes_exact_method_factories_through_product_abi() -> None:
    plan = build_plan()
    toolformer = _lane(plan, "toolformer")
    assert len(toolformer["method_program_digest"]) == 64
    assert toolformer["blockers"] == ()


def test_every_remaining_non_benchmark_execution_input_is_typed_and_digest_bound() -> None:
    plan = build_plan()
    for row in plan["lanes"]:
        parameters = tuple(row["execution_requirement_parameters"])
        kinds = tuple(row["execution_requirement_kinds"])
        digests = tuple(row["execution_requirement_digests"])
        assert len(parameters) == len(kinds) == len(digests)
        assert len(parameters) == len(set(parameters))
        assert all(kind in {
            "capability_id",
            "capability_closure",
            "paper_option",
        } for kind in kinds)
        assert all(
            len(digest) == 64
            and all(ch in "0123456789abcdef" for ch in digest)
            for digest in digests
        )
