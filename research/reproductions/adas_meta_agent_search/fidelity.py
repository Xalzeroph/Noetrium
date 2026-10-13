from __future__ import annotations

from dataclasses import dataclass


ADAS_AUDITED_COMMIT = "2702bee8fefda42255efc5be9f60e3bd3db96ae4"


@dataclass(frozen=True, slots=True)
class ADASMetaAgentSearchFidelity:
    """Paper-era MGSM Meta Agent Search contract for the ICLR 2025 paper."""

    paper_uri: str = (
        "https://proceedings.iclr.cc/paper_files/paper/2025/hash/"
        "36b7acf6f6010652b3f2a433774a66fe-Abstract-Conference.html"
    )
    source_repository: str = "https://github.com/ShengranHu/ADAS"
    audited_commit: str = ADAS_AUDITED_COMMIT
    source_artifact: str = "_mgsm/search.py"
    prompt_artifact: str = "_mgsm/mgsm_prompt.py"
    benchmark: str = "mgsm"

    search_object: str = "executable_agent_code"
    archive_driven_generation: bool = True
    initial_archive_names: tuple[str, ...] = (
        "Chain-of-Thought",
        "Self-Consistency with Chain-of-Thought",
        "Self-Refine (Reflexion)",
        "LLM Debate",
        "Step-back Abstraction",
        "Quality-Diversity",
        "Dynamic Assignment of Roles",
    )

    reflection_passes_per_generation: int = 2
    generation_budget: int = 30
    candidate_execution_attempt_budget: int = 3

    validation_size: int = 128
    test_size: int = 800
    shuffle_seed: int = 0
    repetitions: int = 1
    low_accuracy_debug_threshold: float = 0.01

    meta_model: str = "gpt-4o-2024-05-13"
    candidate_default_model: str = "gpt-3.5-turbo-0125"
    meta_temperature: float = 0.8
    meta_max_output_tokens: int = 4096

    bootstrap_samples: int = 100000
    bootstrap_confidence_level: float = 0.95

    candidate_execution_required: bool = True
    fitness_recorded_in_archive: bool = True
    generation_recorded_in_archive: bool = True
    failed_candidate_debug_regeneration: bool = True
    untrusted_generated_code: bool = True

    # The released source performs n -= 1 inside a for loop on failures.
    # This has no effect on the next loop value and is part of the audited behavior.
    ineffective_generation_decrement: bool = True

    @property
    def initial_archive_size(self) -> int:
        return len(self.initial_archive_names)

    def __post_init__(self) -> None:
        if len(self.audited_commit) != 40:
            raise ValueError("ADAS audited commit must be a git SHA")
        if self.source_artifact != "_mgsm/search.py":
            raise ValueError("formal ADAS lane must bind the paper-era MGSM search")
        if self.benchmark != "mgsm":
            raise ValueError("formal ADAS lane must bind MGSM")
        if self.search_object != "executable_agent_code":
            raise ValueError("ADAS Meta Agent Search evolves executable agent code")
        if not self.archive_driven_generation:
            raise ValueError("ADAS candidate generation must be archive-conditioned")
        if self.initial_archive_names != (
            "Chain-of-Thought",
            "Self-Consistency with Chain-of-Thought",
            "Self-Refine (Reflexion)",
            "LLM Debate",
            "Step-back Abstraction",
            "Quality-Diversity",
            "Dynamic Assignment of Roles",
        ):
            raise ValueError("ADAS MGSM initial archive order drifted")
        if self.reflection_passes_per_generation != 2:
            raise ValueError("ADAS performs exactly two meta-reflection passes")
        if (self.generation_budget, self.candidate_execution_attempt_budget) != (30, 3):
            raise ValueError("ADAS MGSM generation/debug budgets drifted")
        if (
            self.validation_size,
            self.test_size,
            self.shuffle_seed,
            self.repetitions,
        ) != (128, 800, 0, 1):
            raise ValueError("ADAS MGSM search/test split semantics drifted")
        if self.low_accuracy_debug_threshold != 0.01:
            raise ValueError("ADAS low-accuracy debug threshold drifted")
        if (
            self.meta_model != "gpt-4o-2024-05-13"
            or self.candidate_default_model != "gpt-3.5-turbo-0125"
            or self.meta_temperature != 0.8
            or self.meta_max_output_tokens != 4096
        ):
            raise ValueError("ADAS paper-era model-call defaults drifted")
        if (
            self.bootstrap_samples != 100000
            or self.bootstrap_confidence_level != 0.95
        ):
            raise ValueError("ADAS bootstrap fitness semantics drifted")
        if not all(
            (
                self.candidate_execution_required,
                self.fitness_recorded_in_archive,
                self.generation_recorded_in_archive,
                self.failed_candidate_debug_regeneration,
                self.untrusted_generated_code,
                self.ineffective_generation_decrement,
            )
        ):
            raise ValueError("ADAS executable-search fidelity drifted")


ADAS_META_AGENT_SEARCH_FIDELITY = ADASMetaAgentSearchFidelity()


__all__ = [
    "ADAS_AUDITED_COMMIT",
    "ADAS_META_AGENT_SEARCH_FIDELITY",
    "ADASMetaAgentSearchFidelity",
]
