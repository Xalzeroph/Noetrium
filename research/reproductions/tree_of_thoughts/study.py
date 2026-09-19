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
from research.benchmarks.game24 import GAME24_BENCHMARK_ID, GAME24_PAPER_SPLIT

from .fidelity import TREE_OF_THOUGHTS_GAME24_FIDELITY, TREE_OF_THOUGHTS_REFERENCE_FIDELITY


TOT_GAME24_RELEASED_TRIAL_PROTOCOL = ExperimentTrialProtocolIdentity(
    "tree-of-thoughts.game24.released-bfs.v1",
    canonical_digest(
        {
            "task_range": [
                TREE_OF_THOUGHTS_GAME24_FIDELITY.task_start_index,
                TREE_OF_THOUGHTS_GAME24_FIDELITY.task_end_index_exclusive,
            ],
            "backend": TREE_OF_THOUGHTS_GAME24_FIDELITY.backend,
            "temperature": TREE_OF_THOUGHTS_GAME24_FIDELITY.temperature,
            "generation": TREE_OF_THOUGHTS_GAME24_FIDELITY.generation_mode,
            "evaluation": TREE_OF_THOUGHTS_GAME24_FIDELITY.evaluation_mode,
            "selection": TREE_OF_THOUGHTS_GAME24_FIDELITY.selection_mode,
            "n_generate_sample": TREE_OF_THOUGHTS_GAME24_FIDELITY.n_generate_sample,
            "n_evaluate_sample": TREE_OF_THOUGHTS_GAME24_FIDELITY.n_evaluate_sample,
            "n_select_sample": TREE_OF_THOUGHTS_GAME24_FIDELITY.n_select_sample,
            "search_steps": TREE_OF_THOUGHTS_GAME24_FIDELITY.search_steps,
        }
    ),
)


def build_tot_game24_released_study(benchmark: BenchmarkTaskSet) -> ResearchStudyDefinition:
    if benchmark.benchmark_id != GAME24_BENCHMARK_ID:
        raise ValueError("Tree of Thoughts study requires the Game24 benchmark cut")
    benchmark.selected_tasks(GAME24_PAPER_SPLIT)
    return Study(
        project_id="tree-of-thoughts-reproduction",
        study_id="tot-game24-released-bfs",
        benchmark=benchmark,
        benchmark_split_id=GAME24_PAPER_SPLIT,
        method=StudyParticipant(
            role="reasoner",
            kind="agent",
            implementation="tree-of-thoughts",
            treatment="bfs-propose-value-greedy",
            configurations=("tot.game24.bfs", "tot.game24.prompt"),
        ),
        models={
            "reasoner": StudyModel(
                "model.tot.reasoner",
                prompt="tot.game24.prompt",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "task_success",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="task_success",
                scale="binary",
                domain="game24",
            ),
            MeasurementDefinition.scalar(
                "model_call_count",
                schema_id="noetrium.measurement.count.v1",
                unit="call",
                semantic_kind="resource_usage",
                scale="count",
                domain="game24",
            ),
        ),
        trial=TOT_GAME24_RELEASED_TRIAL_PROTOCOL,
        repetitions=1,
        seeds=("paper-default",),
        limits=TrialBudget(
            "tot-game24-four-search-steps",
            max_steps=TREE_OF_THOUGHTS_GAME24_FIDELITY.search_steps,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()



__all__ = ["TOT_GAME24_RELEASED_TRIAL_PROTOCOL", "build_tot_game24_released_study"]
