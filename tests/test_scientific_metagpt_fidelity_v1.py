from research.reproductions.metagpt_software_company import METAGPT_SOFTWARE_COMPANY_FIDELITY


def test_metagpt_preserves_role_specialized_software_company_sop() -> None:
    fidelity = METAGPT_SOFTWARE_COMPANY_FIDELITY
    assert fidelity.philosophy == "Code=SOP(Team)"
    assert fidelity.core_roles == (
        "ProductManager",
        "Architect",
        "ProjectManager",
        "Engineer",
    )
    assert fidelity.default_round_budget == 5


def test_metagpt_preserves_artifact_driven_action_dependency_chain() -> None:
    fidelity = METAGPT_SOFTWARE_COMPANY_FIDELITY
    assert fidelity.sop_edges == (
        ("BossRequirement", "ProductManager", "WritePRD"),
        ("WritePRD", "Architect", "WriteDesign"),
        ("WriteDesign", "ProjectManager", "WriteTasks"),
        ("WriteTasks", "Engineer", "WriteCode"),
    )
    assert fidelity.engineer_optional_code_review
    assert fidelity.engineer_writes_workspace_files
    assert fidelity.role_memory_is_action_addressable
    assert fidelity.artifacts_drive_downstream_roles
