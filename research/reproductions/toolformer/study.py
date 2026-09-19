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
from research.benchmarks.toolformer_eval import TOOLFORMER_BENCHMARK_ID

from .fidelity import TOOLFORMER_FIDELITY
from .program import build_toolformer_method_program


def toolformer_trial_protocol(
    tool_capability_ids: tuple[str, ...],
    *,
    tools_enabled: bool,
) -> ExperimentTrialProtocolIdentity:
    program = build_toolformer_method_program(
        tool_capability_ids,
        tools_enabled=tools_enabled,
    )
    return ExperimentTrialProtocolIdentity(
        (
            "toolformer.neurips2023.tools-enabled.v1"
            if tools_enabled
            else "toolformer.neurips2023.tools-disabled.v1"
        ),
        canonical_digest({
            "program_digest": program.program_digest,
            "publication_id": TOOLFORMER_FIDELITY.publication_id,
            "tools_enabled": tools_enabled,
            "tool_capability_ids": (
                tool_capability_ids if tools_enabled else ()
            ),
            "api_top_k": TOOLFORMER_FIDELITY.evaluation_api_top_k,
            "max_api_calls_per_input": (
                TOOLFORMER_FIDELITY.evaluation_max_api_calls_per_input
            ),
        }),
    )


def build_toolformer_study(
    benchmark: BenchmarkTaskSet,
    *,
    split_id: str,
    tool_capability_ids: tuple[str, ...],
    tools_enabled: bool = True,
) -> ResearchStudyDefinition:
    if benchmark.benchmark_id != TOOLFORMER_BENCHMARK_ID:
        raise ValueError("Toolformer study requires toolformer-eval")
    if not benchmark.selected_tasks(split_id):
        raise ValueError("Toolformer study requires a non-empty split")
    program = build_toolformer_method_program(
        tool_capability_ids,
        tools_enabled=tools_enabled,
    )
    treatment = "toolformer" if tools_enabled else "toolformer-disabled"
    return Study(
        project_id="toolformer-neurips2023-reproduction",
        study_id=f"toolformer-{split_id}-{treatment}",
        benchmark=benchmark,
        benchmark_split_id=split_id,
        method=StudyParticipant(
            role="toolformer",
            kind="agent_method",
            implementation="toolformer-paper-era",
            treatment=treatment,
            capabilities=(
                tool_capability_ids if tools_enabled else ()
            ),
            configurations=(
                "toolformer.gpt-j-api-aware-decoding",
                f"toolformer.tools-enabled:{str(tools_enabled).lower()}",
            ),
        ),
        models={
            "toolformer": StudyModel(
                "model.toolformer.gpt-j",
                prompt="toolformer.zero-shot.paper-era",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "task_success",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="task_success",
                scale="binary",
                domain="toolformer",
            ),
            MeasurementDefinition.scalar(
                "tool_call_count",
                schema_id="noetrium.measurement.count.v1",
                unit="tool_call",
                semantic_kind="tool_usage",
                scale="count",
                domain="toolformer",
            ),
            MeasurementDefinition.scalar(
                "model_call_count",
                schema_id="noetrium.measurement.count.v1",
                unit="model_call",
                semantic_kind="model_usage",
                scale="count",
                domain="toolformer",
            ),
        ),
        trial=toolformer_trial_protocol(
            tool_capability_ids,
            tools_enabled=tools_enabled,
        ),
        repetitions=1,
        seeds=("0",),
        limits=TrialBudget(
            f"toolformer-{treatment}",
            max_steps=8,
            max_model_calls=2 if tools_enabled else 1,
            max_working_seconds=300.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()


__all__ = ["build_toolformer_study", "toolformer_trial_protocol"]
