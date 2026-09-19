from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.experiment.api import ExperimentTrialProtocolIdentity
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkTaskSet,
    MeasurementDefinition,
    ReplayLevel,
    ResearchStudyDefinition,
    Study,
    StudyModel,
    StudyParticipant,
    TrialBudget,
)
from research.benchmarks.gats_synthetic import (
    GATS_STRESS_REVISION,
    GATS_STRESS_SPLIT,
    GATS_STRESS_TASK_COUNT,
    GATS_SYNTHETIC_BENCHMARK_ID,
)

from .fidelity import GATS_REPRODUCIBILITY_FIDELITY

GATS_STRESS_B20_TRIAL_PROTOCOL = ExperimentTrialProtocolIdentity(
    "gats.stress-12x10.b20.pre-arxiv-source.v1",
    canonical_digest({
        "benchmark_revision": GATS_STRESS_REVISION,
        "search_budget": 20,
        "c_puct": GATS_REPRODUCIBILITY_FIDELITY.stress_c_puct,
        "max_steps": GATS_REPRODUCIBILITY_FIDELITY.stress_max_steps,
        "transition_semantics": GATS_REPRODUCIBILITY_FIDELITY.stress_transition_semantics,
        "layered_world_model_used": GATS_REPRODUCIBILITY_FIDELITY.stress_uses_layered_world_model,
    }),
)

def build_gats_stress_b20_study(benchmark: BenchmarkTaskSet) -> ResearchStudyDefinition:
    if benchmark.benchmark_id != GATS_SYNTHETIC_BENCHMARK_ID or benchmark.revision_id != GATS_STRESS_REVISION:
        raise ValueError("GATS stress study requires the frozen 12x10 synthetic cut")
    if len(benchmark.selected_tasks(GATS_STRESS_SPLIT)) != GATS_STRESS_TASK_COUNT:
        raise ValueError("GATS stress b=20 study requires all 120 tasks")
    return Study(
        project_id="gats-reproduction",
        study_id="gats-stress-b20-source-cut",
        benchmark=benchmark,
        benchmark_split_id=GATS_STRESS_SPLIT,
        method=StudyParticipant(
            role="planner",
            kind="agent",
            implementation="gats",
            treatment="stress-script-gats-b20",
            configurations=(
                "gats.stress.search-budget-20",
                "gats.stress.direct-transition",
            ),
        ),
        models={},
        measurements=(
            MeasurementDefinition.scalar(
                "task_success",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="task_success",
                scale="binary",
                domain="gats-synthetic",
            ),
            MeasurementDefinition.scalar(
                "search_nodes",
                schema_id="noetrium.measurement.count.v1",
                unit="node",
                semantic_kind="search_compute",
                scale="count",
                domain="gats-synthetic",
            ),
            MeasurementDefinition.scalar(
                "plan_cost",
                schema_id="noetrium.measurement.scalar.v1",
                unit="cost",
                semantic_kind="plan_cost",
                scale="continuous",
                domain="gats-synthetic",
            ),
        ),
        trial=GATS_STRESS_B20_TRIAL_PROTOCOL,
        repetitions=1,
        seeds=tuple(str(seed) for seed in GATS_REPRODUCIBILITY_FIDELITY.stress_seeds),
        limits=TrialBudget(
            "gats-stress-max-steps-35",
            max_steps=GATS_REPRODUCIBILITY_FIDELITY.stress_max_steps,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()

__all__ = ["GATS_STRESS_B20_TRIAL_PROTOCOL", "build_gats_stress_b20_study"]
