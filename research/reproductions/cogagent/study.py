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
from research.benchmarks.mind2web import MIND2WEB_BENCHMARK_ID

from .fidelity import COGAGENT_FIDELITY
from .program import COGAGENT_METHOD_PROGRAM

COGAGENT_MIND2WEB_TRIAL_PROTOCOL = ExperimentTrialProtocolIdentity(
    "cogagent.cvpr2024.mind2web.v1",
    canonical_digest({
        "program_digest": COGAGENT_METHOD_PROGRAM.program_digest,
        "paper_input_resolution": COGAGENT_FIDELITY.input_resolution,
        "input_representation": COGAGENT_FIDELITY.gui_input_representation,
        "operation_types": COGAGENT_FIDELITY.mind2web_operation_types,
        "candidate_policy": "benchmark-provided-top-k",
    }),
)


def build_cogagent_mind2web_study(
    benchmark: BenchmarkTaskSet,
    *,
    split_id: str,
) -> ResearchStudyDefinition:
    if benchmark.benchmark_id != MIND2WEB_BENCHMARK_ID:
        raise ValueError("CogAgent study requires Mind2Web")
    if not benchmark.selected_tasks(split_id):
        raise ValueError("CogAgent Mind2Web study requires a non-empty split")
    return Study(
        project_id="cogagent-cvpr2024-reproduction",
        study_id=f"cogagent-mind2web-{split_id}",
        benchmark=benchmark,
        benchmark_split_id=split_id,
        method=StudyParticipant(
            role="cogagent",
            kind="visual_gui_agent",
            implementation="cogagent-18b-paper-era",
            treatment="screenshot-only",
            configurations=("cogagent.cvpr2024.gui-policy",),
        ),
        models={
            "cogagent": StudyModel(
                "model.cogagent-18b",
                prompt="cogagent.mind2web.paper-era",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "step_success_rate",
                schema_id="noetrium.measurement.scalar.v1",
                unit="ratio",
                semantic_kind="step_success",
                scale="ratio",
                domain="mind2web",
            ),
            MeasurementDefinition.scalar(
                "model_call_count",
                schema_id="noetrium.measurement.count.v1",
                unit="model_call",
                semantic_kind="model_usage",
                scale="count",
                domain="mind2web",
            ),
        ),
        trial=COGAGENT_MIND2WEB_TRIAL_PROTOCOL,
        repetitions=1,
        seeds=("0",),
        limits=TrialBudget(
            "cogagent-mind2web",
            max_steps=4,
            max_model_calls=1,
            max_working_seconds=300.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()


__all__ = [
    "COGAGENT_MIND2WEB_TRIAL_PROTOCOL",
    "build_cogagent_mind2web_study",
]
