from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.research.provenance import MethodSourceLane, MethodSourceLaneKind
from .source import SOURCE_PRE_ARXIV_REPRODUCIBILITY_CUT

GATS_PAPER_URI = "https://arxiv.org/abs/2607.08894"
@dataclass(frozen=True, slots=True)
class GatsReproducibilityFidelity:
    source: MethodSourceLane = SOURCE_PRE_ARXIV_REPRODUCIBILITY_CUT
    main_task_count: int = 100
    main_seeds: tuple[int, ...] = (42, 123, 456)
    main_backend: str = "mock"
    main_task_generation_seeded_before_generation: bool = False
    main_generator_uses_random_choice_and_shuffle: bool = True
    stress_categories: int = 12
    stress_tasks_per_category: int = 10
    stress_task_count: int = 120
    stress_seeds: tuple[int, ...] = (42, 123, 456)
    stress_gats_budgets: tuple[int, ...] = (10, 20, 50)
    stress_lats_budgets: tuple[int, ...] = (10, 20)
    stress_max_steps: int = 35
    stress_c_puct: float = 1.0
    stress_uses_layered_world_model: bool = False
    stress_transition_semantics: str = "direct_action_apply_plus_state_value_ucb"
    paper_world_model_layers: tuple[str, ...] = ("symbolic", "learned_statistics", "llm_fallback")

    def __post_init__(self) -> None:
        if self.source.kind is not MethodSourceLaneKind.OFFICIAL_EXECUTABLE:
            raise ValueError("GATS reproducibility source must remain official executable")
        if self.main_task_generation_seeded_before_generation:
            raise ValueError("GATS main task generator is not seeded before task construction in this cut")
        if not self.main_generator_uses_random_choice_and_shuffle:
            raise ValueError("GATS main generator randomness must remain explicit")
        if (self.stress_categories, self.stress_tasks_per_category, self.stress_task_count) != (12, 10, 120):
            raise ValueError("GATS stress task matrix drifted")
        if self.stress_seeds != (42, 123, 456):
            raise ValueError("GATS stress seeds drifted")
        if self.stress_gats_budgets != (10, 20, 50) or self.stress_lats_budgets != (10, 20):
            raise ValueError("GATS stress search budgets drifted")
        if (self.stress_max_steps, self.stress_c_puct) != (35, 1.0):
            raise ValueError("GATS stress planner configuration drifted")
        if self.stress_uses_layered_world_model:
            raise ValueError("stress script must not be used as evidence for layered-world-model execution")

GATS_REPRODUCIBILITY_FIDELITY = GatsReproducibilityFidelity()

__all__ = [
    "GATS_PAPER_URI",
    "GATS_REPRODUCIBILITY_FIDELITY",
    "GatsReproducibilityFidelity",
]
