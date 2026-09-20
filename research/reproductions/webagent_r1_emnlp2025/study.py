from __future__ import annotations
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.experiment.api import ExperimentTrialProtocolIdentity
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkTaskSet, MeasurementDefinition, ReplayLevel, ResearchStudyDefinition,
    Study, StudyModel, StudyParticipant, TrialBudget,
)
from .benchmark import require_webagent_r1_benchmark
from .fidelity import WEBAGENT_R1_FIDELITY
from .program import WEBAGENT_R1_METHOD_PROGRAM

def webagent_r1_trial_protocol(benchmark: BenchmarkTaskSet, *, split_id: str) -> ExperimentTrialProtocolIdentity:
    selected = require_webagent_r1_benchmark(benchmark, split_id=split_id)
    return ExperimentTrialProtocolIdentity(
        "webagent-r1.2025.paper-protocol.v1",
        canonical_digest({
            "paper_uri": WEBAGENT_R1_FIDELITY.paper_uri,
            "method_program_digest": WEBAGENT_R1_METHOD_PROGRAM.program_digest,
            "benchmark_id": benchmark.benchmark_id,
            "benchmark_cut_digest": benchmark.cut_digest,
            "split_id": split_id,
            "task_ids": tuple(row.task_id for row in selected),
            "phase_ids": WEBAGENT_R1_FIDELITY.phase_ids,
        }),
    )

def build_webagent_r1_study(benchmark: BenchmarkTaskSet, *, split_id: str) -> ResearchStudyDefinition:
    trial = webagent_r1_trial_protocol(benchmark, split_id=split_id)
    return Study(
        project_id="webagent-r1-2025-reproduction",
        study_id=f"webagent-r1-2025-{benchmark.benchmark_id}-{split_id}",
        benchmark=benchmark,
        benchmark_split_id=split_id,
        method=StudyParticipant(
            role="webagent-r1_agent",
            kind="agent_method",
            implementation="webagent-r1",
            treatment="emnlp-2025-paper-protocol",
            capabilities=("model.generate",),
            configurations=WEBAGENT_R1_FIDELITY.phase_ids,
        ),
        models={"controller": StudyModel("model.webagent-r1.paper-era", prompt="webagent-r1.paper-protocol")},
        measurements=(
            MeasurementDefinition.scalar("task_success", schema_id="noetrium.measurement.ratio.v1", unit="ratio", semantic_kind="task_success", scale="continuous", domain=benchmark.benchmark_id),
            MeasurementDefinition.scalar("agent_phase_count", schema_id="noetrium.measurement.count.v1", unit="phase", semantic_kind="agent_phase_count", scale="count", domain="webagent-r1"),
        ),
        trial=trial,
        repetitions=1,
        seeds=("paper-protocol",),
        limits=TrialBudget("webagent-r1-2025-budget", max_steps=256, max_turns=128, max_model_calls=128, max_working_seconds=3600.0),
        replay_level=ReplayLevel.OBSERVATIONAL,
        repetition_timeout_seconds=3600.0,
    ).build()

__all__ = ["build_webagent_r1_study", "webagent_r1_trial_protocol"]
