from __future__ import annotations

from dataclasses import dataclass


AI_SCIENTIST_V2_REPOSITORY = "SakanaAI/AI-Scientist-v2"
AI_SCIENTIST_V2_SOURCE_COMMIT = "940d59b9008f8d157f03a23e50e49fd81c0a4d11"


@dataclass(frozen=True, slots=True)
class AIScientistV2Fidelity:
    repository: str = AI_SCIENTIST_V2_REPOSITORY
    source_commit: str = AI_SCIENTIST_V2_SOURCE_COMMIT
    paper_arxiv: str = "2504.08066"
    launcher_source: str = "launch_scientist_bfts.py"
    config_source: str = "bfts_config.yaml"
    manager_source: str = "ai_scientist/treesearch/agent_manager.py"
    method_journal_source: str = "ai_scientist/treesearch/journal.py"
    parallel_workers: int = 4
    stage_iteration_budgets: tuple[int, ...] = (20, 12, 12, 18)
    generic_improvement_steps: int = 5
    multi_seed_count: int = 3
    execution_timeout_seconds: int = 3600
    max_debug_depth: int = 3
    debug_probability: float = 0.5
    draft_count: int = 3
    copy_data_into_workspace: bool = True
    generate_report: bool = True
    citation_rounds: int = 20
    writeup_retries: int = 3
    default_writeup_type: str = "icbinb"
    default_writeup_page_limit: int = 4
    normal_writeup_page_limit: int = 8
    method_journal_role: str = "downstream_search_state"
    kernel_journal_remains_platform_authority: bool = True
    human_authored_template_required: bool = False
    experiment_manager_guided_tree_search: bool = True
    text_and_vlm_review: bool = True

    def __post_init__(self) -> None:
        if len(self.source_commit) != 40:
            raise ValueError("AI Scientist v2 source commit must be a full git SHA")
        if self.parallel_workers != 4 or self.stage_iteration_budgets != (20, 12, 12, 18):
            raise ValueError("AI Scientist v2 parallel stage budgets drifted")
        if (self.generic_improvement_steps, self.multi_seed_count, self.execution_timeout_seconds) != (5, 3, 3600):
            raise ValueError("AI Scientist v2 execution budget drifted")
        if (self.max_debug_depth, self.debug_probability, self.draft_count) != (3, 0.5, 3):
            raise ValueError("AI Scientist v2 search policy drifted")
        if not self.copy_data_into_workspace or not self.generate_report:
            raise ValueError("AI Scientist v2 workspace/report policy drifted")
        if (self.citation_rounds, self.writeup_retries) != (20, 3):
            raise ValueError("AI Scientist v2 writeup budget drifted")
        if (self.default_writeup_type, self.default_writeup_page_limit, self.normal_writeup_page_limit) != (
            "icbinb",
            4,
            8,
        ):
            raise ValueError("AI Scientist v2 writeup format drifted")
        if self.method_journal_role != "downstream_search_state":
            raise ValueError("AI Scientist v2 method journal must remain downstream state")
        if not self.kernel_journal_remains_platform_authority:
            raise ValueError("AI Scientist v2 must not replace the platform journal authority")
        if self.human_authored_template_required:
            raise ValueError("AI Scientist v2 must remain template-independent")
        if not self.experiment_manager_guided_tree_search or not self.text_and_vlm_review:
            raise ValueError("AI Scientist v2 core research-loop semantics drifted")


AI_SCIENTIST_V2_FIDELITY = AIScientistV2Fidelity()


__all__ = [
    "AI_SCIENTIST_V2_FIDELITY",
    "AI_SCIENTIST_V2_REPOSITORY",
    "AI_SCIENTIST_V2_SOURCE_COMMIT",
    "AIScientistV2Fidelity",
]
