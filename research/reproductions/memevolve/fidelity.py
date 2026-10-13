from __future__ import annotations

from dataclasses import dataclass


MEMEVOLVE_CODE_COMMIT = "75e6b1a32f94066f1fcc44f3a1dfae6bd537c6d1"


@dataclass(frozen=True, slots=True)
class MemEvolveFidelity:
    """Mechanism-level fidelity for MemEvolve's dual meta-evolution loop.

    The memory architecture search policy and candidate memory semantics remain
    method-owned. Noetrium may own generic candidate isolation, artifact lineage,
    checkpoint/recovery and experiment evaluation, but must not collapse this
    method into a generic memory-management authority.
    """

    paper_uri: str = "https://arxiv.org/abs/2512.18746"
    source_repository: str = "https://github.com/bingreeky/MemEvolve"
    audited_code_commit: str = MEMEVOLVE_CODE_COMMIT
    code_root: str = "Flash-Searcher-main/MemEvolve"
    evolves_memory_content: bool = True
    evolves_memory_architecture: bool = True
    manual_phases: tuple[str, ...] = (
        "analyze_trajectories",
        "generate_memory_system",
        "create_implementation",
        "validate_system",
    )
    round_process: tuple[str, ...] = (
        "collect_base_logs",
        "generate_candidates",
        "tournament_base_plus_candidates",
        "finals_top_t_on_extended_tasks",
        "select_winner_as_next_base",
    )
    candidate_generation_independent: bool = True
    same_task_tournament_required: bool = True
    winner_becomes_next_round_base: bool = True
    checkpoint_on_auto_evolution_error: bool = True

    def __post_init__(self) -> None:
        if len(self.audited_code_commit) != 40:
            raise ValueError("MemEvolve audited code commit must be a git SHA")
        if not self.evolves_memory_content or not self.evolves_memory_architecture:
            raise ValueError("MemEvolve requires dual evolution of content and architecture")
        if self.manual_phases != (
            "analyze_trajectories",
            "generate_memory_system",
            "create_implementation",
            "validate_system",
        ):
            raise ValueError("MemEvolve manual phase order drifted")
        if self.round_process != (
            "collect_base_logs",
            "generate_candidates",
            "tournament_base_plus_candidates",
            "finals_top_t_on_extended_tasks",
            "select_winner_as_next_base",
        ):
            raise ValueError("MemEvolve automatic round semantics drifted")
        if not all((
            self.candidate_generation_independent,
            self.same_task_tournament_required,
            self.winner_becomes_next_round_base,
            self.checkpoint_on_auto_evolution_error,
        )):
            raise ValueError("MemEvolve tournament/recovery fidelity drifted")


MEMEVOLVE_FIDELITY = MemEvolveFidelity()


__all__ = ["MEMEVOLVE_CODE_COMMIT", "MEMEVOLVE_FIDELITY", "MemEvolveFidelity"]
