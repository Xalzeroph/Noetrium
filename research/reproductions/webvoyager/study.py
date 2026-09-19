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
from research.benchmarks.webvoyager import (
    WEBVOYAGER_BENCHMARK_ID,
    WEBVOYAGER_OFFICIAL_SPLIT,
    WEBVOYAGER_OFFICIAL_TASK_COUNT,
)

from .fidelity import WEBVOYAGER_FIDELITY
from .program import WEBVOYAGER_METHOD_PROGRAM


WEBVOYAGER_ACL2024_TRIAL_PROTOCOL = ExperimentTrialProtocolIdentity(
    "webvoyager.acl2024.official-643.v1",
    canonical_digest({
        "program_digest": WEBVOYAGER_METHOD_PROGRAM.program_digest,
        "source_commit": WEBVOYAGER_FIDELITY.audited_commit,
        "task_count": WEBVOYAGER_OFFICIAL_TASK_COUNT,
        "max_iterations": WEBVOYAGER_FIDELITY.max_iterations,
        "observation_mode": WEBVOYAGER_FIDELITY.observation_mode,
        "action_grammar": WEBVOYAGER_FIDELITY.action_grammar,
        "model_temperature": WEBVOYAGER_FIDELITY.model_temperature,
        "model_seed": WEBVOYAGER_FIDELITY.model_seed,
        "max_output_tokens": WEBVOYAGER_FIDELITY.max_output_tokens,
    }),
)


def build_webvoyager_official_study(
    benchmark: BenchmarkTaskSet,
) -> ResearchStudyDefinition:
    if benchmark.benchmark_id != WEBVOYAGER_BENCHMARK_ID:
        raise ValueError("WebVoyager study requires official WebVoyager cut")
    selected = benchmark.selected_tasks(WEBVOYAGER_OFFICIAL_SPLIT)
    if len(selected) != WEBVOYAGER_OFFICIAL_TASK_COUNT:
        raise ValueError("WebVoyager official study requires exactly 643 tasks")
    return Study(
        project_id="webvoyager-acl2024-reproduction",
        study_id="webvoyager-official-643",
        benchmark=benchmark,
        benchmark_split_id=WEBVOYAGER_OFFICIAL_SPLIT,
        method=StudyParticipant(
            role="agent",
            kind="multimodal_web_agent",
            implementation="webvoyager-paper-era",
            treatment="labeled-screenshot-plus-text",
            capabilities=("environment.act",),
            configurations=(
                "webvoyager.acl2024.policy",
                "webvoyager.acl2024.action-grammar",
            ),
        ),
        models={
            "policy": StudyModel(
                "model.webvoyager.policy",
                prompt="webvoyager.acl2024.prompt",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "task_success",
                schema_id="noetrium.measurement.binary-scalar.v1",
                unit="ratio",
                semantic_kind="task_success",
                scale="binary",
                domain="webvoyager",
            ),
            MeasurementDefinition.scalar(
                "step_count",
                schema_id="noetrium.measurement.count.v1",
                unit="step",
                semantic_kind="interaction_length",
                scale="count",
                domain="webvoyager",
            ),
            MeasurementDefinition.scalar(
                "model_call_count",
                schema_id="noetrium.measurement.count.v1",
                unit="model_call",
                semantic_kind="model_usage",
                scale="count",
                domain="webvoyager",
            ),
        ),
        trial=WEBVOYAGER_ACL2024_TRIAL_PROTOCOL,
        repetitions=1,
        seeds=(str(WEBVOYAGER_FIDELITY.model_seed),),
        limits=TrialBudget(
            "webvoyager-acl2024-15-step",
            max_steps=WEBVOYAGER_FIDELITY.max_iterations,
            max_turns=WEBVOYAGER_FIDELITY.max_iterations,
            max_model_calls=WEBVOYAGER_FIDELITY.max_iterations,
            max_working_seconds=3600.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()


__all__ = [
    "WEBVOYAGER_ACL2024_TRIAL_PROTOCOL",
    "build_webvoyager_official_study",
]
