from __future__ import annotations

from scripts.run_reproduction_fleet import build_plan


def _lane(plan: dict, package: str) -> dict:
    rows = [row for row in plan["lanes"] if row["package"] == package]
    assert len(rows) == 1
    return rows[0]


def test_fleet_plan_separates_materialization_from_true_execution_readiness() -> None:
    plan = build_plan()
    assert plan["schema"] == "noetrium.reproduction-fleet-plan.v10"
    assert plan["compile_failure_count"] == 0
    assert plan["research_os_compiled_count"] == plan["executable_reproduction_count"]
    assert plan["graph_node_count"] == plan["executable_reproduction_count"]
    assert len(plan["benchmark_authority_digest"]) == 64
    assert plan["benchmark_authority_binding_count"] >= 1
    assert len(plan["portfolio_digest"]) == 64
    assert len(plan["graph_digest"]) == 64
    assert len(plan["plan_digest"]) == 64
    assert len(plan["prerequisite_manifest_digest"]) == 64
    assert plan["prerequisite_requirement_count"] > 0
    assert plan["prerequisite_stage_counts"]["benchmark"] > 0
    assert "execution_ready_count" not in plan

    states = {
        "benchmark_authority_required",
        "reproduction_closure_required",
        "execution_authority_required",
    }
    assert sum(
        plan[key]
        for key in (
            "benchmark_authority_required_count",
            "reproduction_closure_required_count",
            "execution_authority_required_count",
        )
    ) >= plan["executable_reproduction_count"]
    assert plan["materialization_ready_count"] == plan[
        "execution_authority_required_count"
    ]

    for row in plan["lanes"]:
        assert row["state"] in states
        assert row["study_factory_count"] >= 1
        assert len(row["research_program_digest"]) == 64
        assert len(row["research_graph_semantic_digest"]) == 64
        assert row["research_graph_node_id"] == row["package"] + "::reproduction"
        assert row["blockers"] == ()
        assert row["benchmark_authority_state"] in {"closed", "required"}
        assert row["reproduction_closure_state"] in {"closed", "required"}
        assert row["execution_authority_state"] == "required"
        if row["materialization_ready"]:
            assert row["state"] == "execution_authority_required"
            assert row["benchmark_authority_state"] == "closed"
            assert row["reproduction_closure_state"] == "closed"
            assert row["benchmark_blockers"] == ()
            assert row["materialized_study_count"] >= 1
            assert (
                len(row["study_authority_requirements"])
                == row["materialized_study_count"]
            )
            assert (
                len(row["study_authority_requirement_digests"])
                == row["materialized_study_count"]
            )
            for requirement in row["study_authority_requirements"]:
                assert requirement["package"] == row["package"]
                for key in (
                    "study_definition_digest",
                    "binding_requirement_digest",
                    "trial_protocol_identity_digest",
                    "project_manifest_requirement_digest",
                    "project_manifest_keys_digest",
                    "authority_requirement_digest",
                ):
                    digest = requirement[key]
                    assert len(digest) == 64
                    assert all(ch in "0123456789abcdef" for ch in digest)
                assert requirement["trial_provider_requirement_id"]
                assert requirement["aggregation_requirement_id"]
                assert isinstance(
                    requirement["project_manifest_capability_requirement_ids"],
                    tuple,
                )
                assert isinstance(
                    requirement["project_manifest_method_requirement_keys"],
                    tuple,
                )
                assert isinstance(
                    requirement["project_manifest_configuration_ref_ids"],
                    tuple,
                )
                assert (
                    requirement["trial_provider_requirement_id"]
                    in requirement["project_manifest_capability_requirement_ids"]
                )
                for participant in requirement["participant_requirements"]:
                    assert len(participant) == 5
                    assert len(participant[-1]) == 64
                for model_role in requirement["model_role_requirements"]:
                    assert len(model_role) == 7
                    assert len(model_role[-1]) == 64
        else:
            assert row["materialized_study_count"] == 0
            assert row["study_authority_requirements"] == ()
            assert row["study_authority_requirement_digests"] == ()


def test_fleet_plan_uses_repository_benchmark_authority_instead_of_split_heuristics() -> None:
    plan = build_plan()

    vima = _lane(plan, "vima_embodied")
    assert vima["benchmark_authority_state"] == "closed"
    assert vima["benchmark_selection_count"] >= 1
    assert vima["benchmark_blockers"] == ()
    assert vima["reproduction_closure_state"] == "closed"
    assert vima["state"] == "execution_authority_required"
    assert vima["materialization_ready"] is True
    assert vima["materialized_study_count"] >= 1
    assert vima["study_authority_requirements"]

    react = _lane(plan, "react_alfworld")
    assert react["benchmark_split_axis_consumers"] == ()
    assert react["benchmark_authority_state"] == "required"
    assert react["benchmark_blockers"]
    assert react["state"] == "benchmark_authority_required"
    assert react["materialization_ready"] is False


def test_fleet_plan_keeps_reproduction_closure_independent_from_benchmark_authority() -> None:
    plan = build_plan()
    storm = _lane(plan, "storm_wiki")
    assert storm["execution_requirement_parameters"] == ("search_capability_id",)
    assert storm["execution_requirement_kinds"] == ("capability_id",)
    assert storm["reproduction_closure_state"] == "required"
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
        assert all(
            kind in {"capability_id", "capability_closure", "paper_option"}
            for kind in kinds
        )
        assert all(
            len(digest) == 64
            and all(ch in "0123456789abcdef" for ch in digest)
            for digest in digests
        )
