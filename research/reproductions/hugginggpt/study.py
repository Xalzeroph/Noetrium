from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentTrialProtocolIdentity,
)
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
from research.benchmarks.hugginggpt_paper_tasks import HUGGINGGPT_BENCHMARK_ID

from .fidelity import HUGGINGGPT_FIDELITY
from .program import build_hugginggpt_method_program


def hugginggpt_trial_protocol(
    expert_capability_ids: tuple[str, ...],
) -> ExperimentTrialProtocolIdentity:
    program = build_hugginggpt_method_program(expert_capability_ids)
    return ExperimentTrialProtocolIdentity(
        "hugginggpt.neurips2023.paper-tasks.v1",
        canonical_digest({
            "program_digest": program.program_digest,
            "source_commit": HUGGINGGPT_FIDELITY.source_commit,
            "stages": tuple(stage.value for stage in HUGGINGGPT_FIDELITY.stages),
            "expert_capability_ids": expert_capability_ids,
            "dependency_marker": HUGGINGGPT_FIDELITY.dependency_marker,
        }),
    )


def build_hugginggpt_study(
    benchmark: BenchmarkTaskSet,
    *,
    split_id: str,
    expert_capability_ids: tuple[str, ...],
) -> ResearchStudyDefinition:
    if benchmark.benchmark_id != HUGGINGGPT_BENCHMARK_ID:
        raise ValueError("HuggingGPT study requires paper-era task cut")
    if not benchmark.selected_tasks(split_id):
        raise ValueError("HuggingGPT study requires a non-empty split")
    return Study(
        project_id="hugginggpt-neurips2023-reproduction",
        study_id=f"hugginggpt-paper-tasks-{split_id}",
        benchmark=benchmark,
        benchmark_split_id=split_id,
        method=StudyParticipant(
            role="hugginggpt",
            kind="agent_method",
            implementation="hugginggpt-paper-era",
            treatment="four-stage-controller",
            capabilities=expert_capability_ids,
            configurations=("hugginggpt.task-model-execution-response",),
        ),
        models={
            "planner": StudyModel(
                "model.hugginggpt.controller.plan",
                prompt="hugginggpt.task-planning.paper-era",
            ),
            "selector": StudyModel(
                "model.hugginggpt.controller.select-model",
                prompt="hugginggpt.model-selection.paper-era",
            ),
            "aggregator": StudyModel(
                "model.hugginggpt.controller.aggregate",
                prompt="hugginggpt.response-generation.paper-era",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "task_success",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="task_success",
                scale="binary",
                domain="hugginggpt",
            ),
            MeasurementDefinition.scalar(
                "subtask_count",
                schema_id="noetrium.measurement.count.v1",
                unit="subtask",
                semantic_kind="task_decomposition_size",
                scale="count",
                domain="hugginggpt",
            ),
            MeasurementDefinition.scalar(
                "expert_call_count",
                schema_id="noetrium.measurement.count.v1",
                unit="expert_call",
                semantic_kind="expert_model_usage",
                scale="count",
                domain="hugginggpt",
            ),
            MeasurementDefinition.scalar(
                "model_call_count",
                schema_id="noetrium.measurement.count.v1",
                unit="model_call",
                semantic_kind="controller_model_usage",
                scale="count",
                domain="hugginggpt",
            ),
        ),
        trial=hugginggpt_trial_protocol(expert_capability_ids),
        repetitions=1,
        seeds=("0",),
        limits=TrialBudget(
            "hugginggpt-paper-era",
            max_steps=4096,
            max_model_calls=4096,
            max_working_seconds=3600.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()


__all__ = ["build_hugginggpt_study", "hugginggpt_trial_protocol"]
