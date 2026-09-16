from __future__ import annotations

from dataclasses import dataclass


CHATDEV_V1_AUDITED_TAG = "v1.0.0"
CHATDEV_V1_AUDITED_COMMIT = "acb93cf3d15cec5b9ee6eec0850ddd3932164329"

CHATDEV_V1_RECRUITMENTS = (
    "Chief Executive Officer",
    "Counselor",
    "Chief Human Resource Officer",
    "Chief Product Officer",
    "Chief Technology Officer",
    "Programmer",
    "Code Reviewer",
    "Software Test Engineer",
    "Chief Creative Officer",
)


@dataclass(frozen=True, slots=True)
class ChatDevV1ReferenceFidelity:
    """Original ChatDev v1.0.0 software-company semantics from the official tag."""

    source_repository: str = "https://github.com/OpenBMB/ChatDev"
    audited_tag: str = CHATDEV_V1_AUDITED_TAG
    audited_commit: str = CHATDEV_V1_AUDITED_COMMIT
    chain_source: str = "CompanyConfig/Default/ChatChainConfig.json"
    phase_source: str = "CompanyConfig/Default/PhaseConfig.json"
    role_source: str = "CompanyConfig/Default/RoleConfig.json"
    runtime_source: str = "chatdev/chat_chain.py"
    composed_phase_source: str = "chatdev/composed_phase.py"
    phase_runtime_source: str = "chatdev/phase.py"
    default_chat_turn_limit: int = 10
    top_level_phase_order: tuple[str, ...] = (
        "DemandAnalysis",
        "LanguageChoose",
        "Coding",
        "CodeCompleteAll",
        "CodeReview",
        "Test",
        "EnvironmentDoc",
        "Manual",
    )
    reflection_phases: tuple[str, ...] = (
        "DemandAnalysis",
        "LanguageChoose",
        "EnvironmentDoc",
    )
    reflection_roles: tuple[str, str] = ("Chief Executive Officer", "Counselor")
    code_complete_cycle_limit: int = 10
    code_complete_max_attempts_per_file: int = 5
    code_review_cycle_limit: int = 3
    test_cycle_limit: int = 3
    nested_composed_phases_supported: bool = False
    clear_structure: bool = True
    brainstorming: bool = False
    gui_design: bool = True
    git_management: bool = False
    self_improve: bool = False
    recruitments: tuple[str, ...] = CHATDEV_V1_RECRUITMENTS

    def __post_init__(self) -> None:
        if len(self.audited_commit) != 40:
            raise ValueError("ChatDev v1 audited commit must be a git SHA")
        if self.top_level_phase_order != (
            "DemandAnalysis",
            "LanguageChoose",
            "Coding",
            "CodeCompleteAll",
            "CodeReview",
            "Test",
            "EnvironmentDoc",
            "Manual",
        ):
            raise ValueError("ChatDev v1 top-level phase order drifted")
        if self.reflection_phases != (
            "DemandAnalysis",
            "LanguageChoose",
            "EnvironmentDoc",
        ):
            raise ValueError("ChatDev v1 reflection phase set drifted")
        if self.reflection_roles != ("Chief Executive Officer", "Counselor"):
            raise ValueError("ChatDev v1 reflection role pair drifted")
        if (
            self.default_chat_turn_limit,
            self.code_complete_cycle_limit,
            self.code_complete_max_attempts_per_file,
            self.code_review_cycle_limit,
            self.test_cycle_limit,
        ) != (10, 10, 5, 3, 3):
            raise ValueError("ChatDev v1 bounded-loop defaults drifted")
        if self.nested_composed_phases_supported:
            raise ValueError("ChatDev v1 must not claim nested composed phases")
        if not self.clear_structure or not self.gui_design:
            raise ValueError("ChatDev v1 default structural/GUI flags drifted")
        if self.brainstorming or self.git_management or self.self_improve:
            raise ValueError("ChatDev v1 must not backport later optional semantics")
        if self.recruitments != CHATDEV_V1_RECRUITMENTS:
            raise ValueError("ChatDev v1 recruitment roster drifted")


CHATDEV_V1_REFERENCE_FIDELITY = ChatDevV1ReferenceFidelity()


__all__ = [
    "CHATDEV_V1_AUDITED_COMMIT",
    "CHATDEV_V1_AUDITED_TAG",
    "CHATDEV_V1_RECRUITMENTS",
    "CHATDEV_V1_REFERENCE_FIDELITY",
    "ChatDevV1ReferenceFidelity",
]
