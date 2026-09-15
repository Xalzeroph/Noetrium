from __future__ import annotations

from dataclasses import dataclass


ADAS_AUDITED_COMMIT = "2702bee8fefda42255efc5be9f60e3bd3db96ae4"


@dataclass(frozen=True, slots=True)
class ADASMetaAgentSearchFidelity:
    """Mechanism-level fidelity contract for Automated Design of Agentic Systems.

    Domain prompts and benchmark-specific evaluation remain reproduction-owned.
    Generated executable agent code is scientific candidate state; generic
    isolation, execution evidence, lineage and recovery remain Platform-owned.
    """

    paper_uri: str = "https://arxiv.org/abs/2408.08435"
    source_repository: str = "https://github.com/ShengranHu/ADAS"
    audited_commit: str = ADAS_AUDITED_COMMIT
    source_artifact: str = "_arc/search.py"
    search_object: str = "executable_agent_code"
    archive_driven_generation: bool = True
    reflection_passes_per_generation: int = 2
    default_generation_budget: int = 25
    default_debug_attempt_budget: int = 3
    candidate_execution_required: bool = True
    fitness_recorded_in_archive: bool = True
    generation_recorded_in_archive: bool = True
    failed_candidate_debug_regeneration: bool = True
    untrusted_generated_code: bool = True

    def __post_init__(self) -> None:
        if len(self.audited_commit) != 40:
            raise ValueError("ADAS audited commit must be a git SHA")
        if self.search_object != "executable_agent_code":
            raise ValueError("ADAS Meta Agent Search evolves executable agent code")
        if not self.archive_driven_generation:
            raise ValueError("ADAS candidate generation must be conditioned on the archive")
        if self.reflection_passes_per_generation != 2:
            raise ValueError("audited ADAS search performs two reflection passes")
        if (self.default_generation_budget, self.default_debug_attempt_budget) != (25, 3):
            raise ValueError("audited ARC ADAS budgets drifted")
        if not all((
            self.candidate_execution_required,
            self.fitness_recorded_in_archive,
            self.generation_recorded_in_archive,
            self.failed_candidate_debug_regeneration,
            self.untrusted_generated_code,
        )):
            raise ValueError("ADAS executable-search fidelity drifted")


ADAS_META_AGENT_SEARCH_FIDELITY = ADASMetaAgentSearchFidelity()


__all__ = [
    "ADAS_AUDITED_COMMIT",
    "ADAS_META_AGENT_SEARCH_FIDELITY",
    "ADASMetaAgentSearchFidelity",
]
