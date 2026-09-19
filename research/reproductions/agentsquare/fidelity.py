from __future__ import annotations

from dataclasses import dataclass, field

from noetrium_platform.foundation.kernel.kernel import canonical_digest

AGENTSQUARE_LATER_OFFICIAL_COMMIT = "8f5b3fe5d8a32f9b59d20370823bef2a2c86928c"


@dataclass(frozen=True, slots=True)
class AgentSquareFidelity:
    paper_uri: str = (
        "https://proceedings.iclr.cc/paper_files/paper/2025/hash/"
        "0ae94013da7cd459402fd77874e09ee3-Abstract-Conference.html"
    )
    source_repository: str = "https://github.com/tsinghua-fib-lab/AgentSquare"
    audited_commit: str = AGENTSQUARE_LATER_OFFICIAL_COMMIT
    module_types: tuple[str, ...] = (
        "planning",
        "reasoning",
        "tooluse",
        "memory",
    )
    mechanisms: tuple[str, ...] = (
        "module_evolution",
        "module_recombination",
        "performance_predictor",
    )
    reported_benchmarks: tuple[str, ...] = (
        "WebShop",
        "ALFWorld",
        "SciWorld",
        "M3Tool",
        "TravelPlanner",
        "PDDL",
    )
    released_alfworld_search_iterations: int = 10
    released_candidate_eval_episodes: int = 50
    released_initial_agent: tuple[str, str, str, str] = (
        "None",
        "IO",
        "None",
        "None",
    )
    released_initial_performance: float = 0.56
    predictor_train_fraction: float = 0.8
    predictor_train_cap: int = 85
    predictor_shuffle_seed: int = 42
    fidelity_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if len(self.audited_commit) != 40:
            raise ValueError("AgentSquare audited commit must be a git SHA")
        if self.module_types != ("planning", "reasoning", "tooluse", "memory"):
            raise ValueError("AgentSquare four-module design space drifted")
        if self.mechanisms != (
            "module_evolution",
            "module_recombination",
            "performance_predictor",
        ):
            raise ValueError("AgentSquare search mechanisms drifted")
        if self.released_alfworld_search_iterations != 10:
            raise ValueError("AgentSquare released ALFWorld iteration budget drifted")
        if self.released_candidate_eval_episodes != 50:
            raise ValueError("AgentSquare released evaluation cardinality drifted")
        object.__setattr__(
            self,
            "fidelity_digest",
            canonical_digest({
                "paper_uri": self.paper_uri,
                "source_repository": self.source_repository,
                "audited_commit": self.audited_commit,
                "module_types": self.module_types,
                "mechanisms": self.mechanisms,
                "reported_benchmarks": self.reported_benchmarks,
                "released_alfworld_search_iterations": (
                    self.released_alfworld_search_iterations
                ),
                "released_candidate_eval_episodes": (
                    self.released_candidate_eval_episodes
                ),
                "released_initial_agent": self.released_initial_agent,
                "released_initial_performance": self.released_initial_performance,
                "predictor_train_fraction": self.predictor_train_fraction,
                "predictor_train_cap": self.predictor_train_cap,
                "predictor_shuffle_seed": self.predictor_shuffle_seed,
            }),
        )


AGENTSQUARE_FIDELITY = AgentSquareFidelity()

__all__ = [
    "AGENTSQUARE_FIDELITY",
    "AGENTSQUARE_LATER_OFFICIAL_COMMIT",
    "AgentSquareFidelity",
]
