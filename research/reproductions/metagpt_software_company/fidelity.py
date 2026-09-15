from __future__ import annotations

from dataclasses import dataclass


METAGPT_PAPER_ERA_COMMIT = "91595daa3b49f1a7bd0ed49e4bea80568455ba00"


@dataclass(frozen=True, slots=True)
class MetaGPTSoftwareCompanyFidelity:
    """Paper-era MetaGPT software-company SOP semantics.

    Role/action subscriptions and software artifacts are method semantics.
    Noetrium may provide generic participant topology, message delivery,
    artifact/effect lineage, model execution and bounded orchestration only.
    """

    paper_uri: str = "https://arxiv.org/abs/2308.00352"
    source_repository: str = "https://github.com/FoundationAgents/MetaGPT"
    audited_commit: str = METAGPT_PAPER_ERA_COMMIT
    philosophy: str = "Code=SOP(Team)"
    core_roles: tuple[str, ...] = (
        "ProductManager",
        "Architect",
        "ProjectManager",
        "Engineer",
    )
    default_round_budget: int = 5
    sop_edges: tuple[tuple[str, str, str], ...] = (
        ("BossRequirement", "ProductManager", "WritePRD"),
        ("WritePRD", "Architect", "WriteDesign"),
        ("WriteDesign", "ProjectManager", "WriteTasks"),
        ("WriteTasks", "Engineer", "WriteCode"),
    )
    engineer_optional_code_review: bool = True
    engineer_writes_workspace_files: bool = True
    role_memory_is_action_addressable: bool = True
    artifacts_drive_downstream_roles: bool = True

    def __post_init__(self) -> None:
        if len(self.audited_commit) != 40:
            raise ValueError("MetaGPT audited commit must be a git SHA")
        if self.philosophy != "Code=SOP(Team)":
            raise ValueError("paper-era MetaGPT SOP philosophy drifted")
        if self.core_roles != ("ProductManager", "Architect", "ProjectManager", "Engineer"):
            raise ValueError("paper-era MetaGPT core software roles drifted")
        if self.default_round_budget != 5:
            raise ValueError("paper-era MetaGPT default round budget drifted")
        if self.sop_edges != (
            ("BossRequirement", "ProductManager", "WritePRD"),
            ("WritePRD", "Architect", "WriteDesign"),
            ("WriteDesign", "ProjectManager", "WriteTasks"),
            ("WriteTasks", "Engineer", "WriteCode"),
        ):
            raise ValueError("MetaGPT SOP dependency chain drifted")
        if not all((
            self.engineer_optional_code_review,
            self.engineer_writes_workspace_files,
            self.role_memory_is_action_addressable,
            self.artifacts_drive_downstream_roles,
        )):
            raise ValueError("MetaGPT artifact/action semantics drifted")


METAGPT_SOFTWARE_COMPANY_FIDELITY = MetaGPTSoftwareCompanyFidelity()


__all__ = [
    "METAGPT_PAPER_ERA_COMMIT",
    "METAGPT_SOFTWARE_COMPANY_FIDELITY",
    "MetaGPTSoftwareCompanyFidelity",
]
