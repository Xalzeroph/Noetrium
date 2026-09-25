from __future__ import annotations

from dataclasses import dataclass

AGENTLESS_AUDITED_COMMIT = "b150f28465a77a81a7f4776384957a4271f5bd69"


@dataclass(frozen=True, slots=True)
class AgentlessFidelity:
    source_repository: str = "https://github.com/OpenAutoCoder/Agentless"
    audited_commit: str = AGENTLESS_AUDITED_COMMIT
    release: str = "v1.5.0"
    stages: tuple[str, ...] = (
        "localization",
        "repair",
        "patch_validation",
    )
    localization_levels: tuple[str, ...] = (
        "file",
        "class_or_function",
        "fine_grained_edit_location",
    )
    autonomous_agent_loop: bool = False
    model_selects_next_tool_action: bool = False
    samples_multiple_candidate_patches: bool = True
    selects_regression_tests: bool = True
    generates_reproduction_tests: bool = True
    reranks_with_validation_results: bool = True
    benchmark_subset: str = "lite"
    benchmark_task_count: int = 300

    def __post_init__(self) -> None:
        if len(self.audited_commit) != 40:
            raise ValueError("Agentless audited commit must be a full git SHA")
        if self.stages != ("localization", "repair", "patch_validation"):
            raise ValueError("Agentless three-stage workflow drifted")
        if self.localization_levels != (
            "file",
            "class_or_function",
            "fine_grained_edit_location",
        ):
            raise ValueError("Agentless hierarchical localization drifted")
        if self.autonomous_agent_loop or self.model_selects_next_tool_action:
            raise ValueError("Agentless must remain non-autonomous")
        if not all((
            self.samples_multiple_candidate_patches,
            self.selects_regression_tests,
            self.generates_reproduction_tests,
            self.reranks_with_validation_results,
        )):
            raise ValueError("Agentless repair/validation semantics drifted")
        if self.benchmark_subset != "lite" or self.benchmark_task_count != 300:
            raise ValueError("Agentless SWE-bench Lite protocol drifted")


AGENTLESS_FIDELITY = AgentlessFidelity()

__all__ = [
    "AGENTLESS_AUDITED_COMMIT",
    "AGENTLESS_FIDELITY",
    "AgentlessFidelity",
]
