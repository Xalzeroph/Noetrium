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
from research.benchmarks.alfworld import (
    ALFWORLD_BENCHMARK_ID,
    ALFWORLD_PAPER_EVAL_SPLIT,
)

from .fidelity import REACT_ALFWORLD_FIDELITY
from .program import REACT_ALFWORLD_METHOD_PROGRAM

REACT_ALFWORLD_RELEASED_TRIAL_PROTOCOL = ExperimentTrialProtocolIdentity(
    "react.alfworld.released-code.v1",
    canonical_digest(
        {
            "program_digest": REACT_ALFWORLD_METHOD_PROGRAM.program_digest,
            "model": REACT_ALFWORLD_FIDELITY.reference_model,
            "temperature": REACT_ALFWORLD_FIDELITY.temperature,
            "max_output_tokens": REACT_ALFWORLD_FIDELITY.max_output_tokens,
            "stop_sequences": REACT_ALFWORLD_FIDELITY.stop_sequences,
            "max_turns": REACT_ALFWORLD_FIDELITY.max_turns,
        }
    ),
)


def build_react_alfworld_released_study(benchmark: BenchmarkTaskSet) -> ResearchStudyDefinition:
    """Author the released-code ReAct ALFWorld sweep through the generic Study compiler."""

    if benchmark.benchmark_id != ALFWORLD_BENCHMARK_ID:
        raise ValueError("ReAct ALFWorld study requires the shared ALFWorld benchmark cut")
    benchmark.selected_tasks(ALFWORLD_PAPER_EVAL_SPLIT)
    return Study(
        project_id="react-alfworld-reproduction",
        study_id="react-alfworld-released-code",
        benchmark=benchmark,
        benchmark_split_id=ALFWORLD_PAPER_EVAL_SPLIT,
        method=StudyParticipant(
            role="agent",
            kind="agent",
            implementation="react",
            treatment="released-code",
            capabilities=("environment.act",),
            configurations=("react.alfworld.prompt",),
        ),
        models={
            "action": StudyModel(
                "model.react.action",
                prompt="react.alfworld.prompt",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "episode_success",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="task_success",
                scale="binary",
                domain="alfworld",
            ),
            MeasurementDefinition.scalar(
                "turn_count",
                schema_id="noetrium.measurement.count.v1",
                unit="turn",
                semantic_kind="resource_usage",
                scale="count",
                domain="alfworld",
            ),
        ),
        trial=REACT_ALFWORLD_RELEASED_TRIAL_PROTOCOL,
        repetitions=1,
        seeds=("42",),
        limits=TrialBudget("react-alfworld-49-turn", max_steps=49),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()



__all__ = [
    "REACT_ALFWORLD_RELEASED_TRIAL_PROTOCOL",
    "build_react_alfworld_released_study",
]
