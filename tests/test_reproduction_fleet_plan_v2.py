from __future__ import annotations

from scripts.run_reproduction_fleet import build_plan


def _lane(plan: dict, package: str) -> dict:
    rows = [row for row in plan["lanes"] if row["package"] == package]
    assert len(rows) == 1
    return rows[0]


def test_fleet_plan_uses_program_requirements_instead_of_runtime_file_guessing() -> None:
    plan = build_plan()
    assert plan["schema"] == "noetrium.reproduction-fleet-plan.v2"
    assert plan["protocol_bound_count"] == 91
    assert all("runtime_binding_missing" not in row["blockers"] for row in plan["lanes"])

    cot = _lane(plan, "chain_of_thought_gsm8k")
    assert cot["state"] == "runnable"
    assert cot["runtime_mode"] == "direct_main"

    adapt = _lane(plan, "adaptagent_acl2025")
    assert adapt["runtime_mode"] == "declarative"
    assert adapt["runtime_ports"] == ("agent_loop",)
    assert "runtime_port_unbound:agent_loop" in adapt["blockers"]
    assert adapt["program_digest"]
    assert adapt["runtime_requirements_digest"]

    chatdev = _lane(plan, "chatdev_v1")
    assert "child_machines" in chatdev["runtime_ports"]
    assert "runtime_port_unbound:child_machines" in chatdev["blockers"]

    worldmm = _lane(plan, "worldmm_memory")
    assert worldmm["runtime_ports"] == ("capabilities", "child_machines")
    assert "worldmm.answer.generate" in worldmm["capability_ids"]
    assert "worldmm.reasoning.generate" in worldmm["capability_ids"]


def test_fleet_plan_resolves_zero_argument_public_method_factory_only() -> None:
    plan = build_plan()
    metagpt = _lane(plan, "metagpt_software_company")
    assert metagpt["program_export"] == "build_metagpt_software_company_method_program()"
    assert metagpt["program_digest"]

    toolformer = _lane(plan, "toolformer")
    assert toolformer["program_export"] is None
    assert "program_factory_requires_binding" in toolformer["blockers"]
