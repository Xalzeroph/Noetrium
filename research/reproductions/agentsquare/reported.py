from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from research.benchmarks.agentboard_pddl import (
    AGENTBOARD_PDDL_BENCHMARK_ID,
    AGENTSQUARE_PDDL_REVISION,
    AGENTSQUARE_PDDL_SPLIT,
)
from research.benchmarks.alfworld import (
    ALFWORLD_BENCHMARK_ID,
    ALFWORLD_PAPER_EVAL_REVISION,
    ALFWORLD_PAPER_EVAL_SPLIT,
)
from research.benchmarks.m3tooleval import (
    AGENTSQUARE_M3TOOL_REVISION,
    AGENTSQUARE_M3TOOL_SPLIT,
    M3TOOLEVAL_BENCHMARK_ID,
)
from research.benchmarks.scienceworld import (
    AGENTSQUARE_SCIENCEWORLD_REVISION,
    AGENTSQUARE_SCIENCEWORLD_SPLIT,
    SCIENCEWORLD_BENCHMARK_ID,
)
from research.benchmarks.travelplanner import (
    AGENTSQUARE_TRAVELPLANNER_REVISION,
    AGENTSQUARE_TRAVELPLANNER_VALIDATION_SPLIT,
    TRAVELPLANNER_BENCHMARK_ID,
)
from research.benchmarks.webshop import (
    AGENTSQUARE_WEBSHOP_REVISION,
    AGENTSQUARE_WEBSHOP_SPLIT,
    WEBSHOP_BENCHMARK_ID,
)


class AgentSquareTreatment(StrEnum):
    FULL = "full"
    WITHOUT_MODULE_EVOLUTION = "without_module_evolution"
    WITHOUT_MODULE_RECOMBINATION = "without_module_recombination"


@dataclass(frozen=True, slots=True)
class AgentSquareReportedScores:
    full: float
    without_module_evolution: float
    without_module_recombination: float

    def for_treatment(self, treatment: AgentSquareTreatment) -> float:
        if treatment is AgentSquareTreatment.FULL:
            return self.full
        if treatment is AgentSquareTreatment.WITHOUT_MODULE_EVOLUTION:
            return self.without_module_evolution
        if treatment is AgentSquareTreatment.WITHOUT_MODULE_RECOMBINATION:
            return self.without_module_recombination
        raise ValueError("unsupported AgentSquare treatment")


@dataclass(frozen=True, slots=True)
class AgentSquareSearchEconomics:
    average_cost_per_iteration_usd: float
    iterations_until_termination: int

    @property
    def reported_total_search_cost_usd(self) -> float:
        return (
            self.average_cost_per_iteration_usd
            * self.iterations_until_termination
        )


@dataclass(frozen=True, slots=True)
class AgentSquareBenchmarkProfile:
    key: str
    benchmark_id: str
    revision_id: str
    evaluation_split_id: str
    primary_measurement_id: str
    primary_semantic_kind: str
    primary_unit: str
    primary_scale: str
    domain: str
    gpt4o_scores: AgentSquareReportedScores
    gpt35_scores: AgentSquareReportedScores
    gpt4o_search: AgentSquareSearchEconomics
    gpt35_search: AgentSquareSearchEconomics


AGENTSQUARE_BENCHMARK_PROFILES = (
    AgentSquareBenchmarkProfile(
        key="webshop",
        benchmark_id=WEBSHOP_BENCHMARK_ID,
        revision_id=AGENTSQUARE_WEBSHOP_REVISION,
        evaluation_split_id=AGENTSQUARE_WEBSHOP_SPLIT,
        primary_measurement_id="reward",
        primary_semantic_kind="task_reward",
        primary_unit="score",
        primary_scale="continuous",
        domain="webshop",
        gpt4o_scores=AgentSquareReportedScores(0.607, 0.564, 0.560),
        gpt35_scores=AgentSquareReportedScores(0.617, 0.595, 0.578),
        gpt4o_search=AgentSquareSearchEconomics(10.51, 18),
        gpt35_search=AgentSquareSearchEconomics(3.16, 23),
    ),
    AgentSquareBenchmarkProfile(
        key="alfworld",
        benchmark_id=ALFWORLD_BENCHMARK_ID,
        revision_id=ALFWORLD_PAPER_EVAL_REVISION,
        evaluation_split_id=ALFWORLD_PAPER_EVAL_SPLIT,
        primary_measurement_id="episode_success",
        primary_semantic_kind="task_success",
        primary_unit="ratio",
        primary_scale="binary",
        domain="alfworld",
        gpt4o_scores=AgentSquareReportedScores(0.695, 0.649, 0.616),
        gpt35_scores=AgentSquareReportedScores(0.651, 0.623, 0.546),
        gpt4o_search=AgentSquareSearchEconomics(13.96, 15),
        gpt35_search=AgentSquareSearchEconomics(4.25, 21),
    ),
    AgentSquareBenchmarkProfile(
        key="scienceworld",
        benchmark_id=SCIENCEWORLD_BENCHMARK_ID,
        revision_id=AGENTSQUARE_SCIENCEWORLD_REVISION,
        evaluation_split_id=AGENTSQUARE_SCIENCEWORLD_SPLIT,
        primary_measurement_id="progress_rate",
        primary_semantic_kind="task_progress",
        primary_unit="ratio",
        primary_scale="continuous",
        domain="scienceworld",
        gpt4o_scores=AgentSquareReportedScores(0.781, 0.736, 0.710),
        gpt35_scores=AgentSquareReportedScores(0.432, 0.288, 0.310),
        gpt4o_search=AgentSquareSearchEconomics(42.14, 9),
        gpt35_search=AgentSquareSearchEconomics(1.92, 8),
    ),
    AgentSquareBenchmarkProfile(
        key="m3tool",
        benchmark_id=M3TOOLEVAL_BENCHMARK_ID,
        revision_id=AGENTSQUARE_M3TOOL_REVISION,
        evaluation_split_id=AGENTSQUARE_M3TOOL_SPLIT,
        primary_measurement_id="success_rate",
        primary_semantic_kind="task_success",
        primary_unit="ratio",
        primary_scale="binary",
        domain="m3tooleval",
        gpt4o_scores=AgentSquareReportedScores(0.524, 0.502, 0.481),
        gpt35_scores=AgentSquareReportedScores(0.285, 0.236, 0.258),
        gpt4o_search=AgentSquareSearchEconomics(26.03, 18),
        gpt35_search=AgentSquareSearchEconomics(2.43, 14),
    ),
    AgentSquareBenchmarkProfile(
        key="travelplanner",
        benchmark_id=TRAVELPLANNER_BENCHMARK_ID,
        revision_id=AGENTSQUARE_TRAVELPLANNER_REVISION,
        evaluation_split_id=AGENTSQUARE_TRAVELPLANNER_VALIDATION_SPLIT,
        primary_measurement_id="commonsense_constraint_micro_pass_rate",
        primary_semantic_kind="constraint_satisfaction",
        primary_unit="ratio",
        primary_scale="continuous",
        domain="travelplanner",
        gpt4o_scores=AgentSquareReportedScores(0.583, 0.577, 0.280),
        gpt35_scores=AgentSquareReportedScores(0.520, 0.483, 0.267),
        gpt4o_search=AgentSquareSearchEconomics(29.75, 8),
        gpt35_search=AgentSquareSearchEconomics(1.84, 9),
    ),
    AgentSquareBenchmarkProfile(
        key="pddl",
        benchmark_id=AGENTBOARD_PDDL_BENCHMARK_ID,
        revision_id=AGENTSQUARE_PDDL_REVISION,
        evaluation_split_id=AGENTSQUARE_PDDL_SPLIT,
        primary_measurement_id="progress_rate",
        primary_semantic_kind="task_progress",
        primary_unit="ratio",
        primary_scale="continuous",
        domain="agentboard-pddl",
        gpt4o_scores=AgentSquareReportedScores(0.669, 0.614, 0.669),
        gpt35_scores=AgentSquareReportedScores(0.219, 0.202, 0.173),
        gpt4o_search=AgentSquareSearchEconomics(26.94, 12),
        gpt35_search=AgentSquareSearchEconomics(2.70, 17),
    ),
)

AGENTSQUARE_BENCHMARK_PROFILE_BY_ID = {
    row.benchmark_id: row for row in AGENTSQUARE_BENCHMARK_PROFILES
}
AGENTSQUARE_BENCHMARK_PROFILE_BY_KEY = {
    row.key: row for row in AGENTSQUARE_BENCHMARK_PROFILES
}

if len(AGENTSQUARE_BENCHMARK_PROFILE_BY_ID) != 6:
    raise RuntimeError("AgentSquare benchmark ids must be unique")
if len(AGENTSQUARE_BENCHMARK_PROFILE_BY_KEY) != 6:
    raise RuntimeError("AgentSquare benchmark keys must be unique")


__all__ = [
    "AGENTSQUARE_BENCHMARK_PROFILES",
    "AGENTSQUARE_BENCHMARK_PROFILE_BY_ID",
    "AGENTSQUARE_BENCHMARK_PROFILE_BY_KEY",
    "AgentSquareBenchmarkProfile",
    "AgentSquareReportedScores",
    "AgentSquareSearchEconomics",
    "AgentSquareTreatment",
]
