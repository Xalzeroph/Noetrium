from __future__ import annotations
from noetrium.api import canonical_digest
from noetrium.api import ExperimentTrialProtocolIdentity
from noetrium.api import (
    BenchmarkTaskSet, MeasurementDefinition, ReplayLevel, ResearchStudyDefinition,
    Study, StudyModel, StudyParticipant, TrialBudget,
)
from .benchmark import require_embodied_videoagent_benchmark
from .fidelity import EMBODIED_VIDEOAGENT_FIDELITY
from .program import EMBODIED_VIDEOAGENT_METHOD_PROGRAM

def embodied_videoagent_trial_protocol(benchmark: BenchmarkTaskSet, *, split_id: str) -> ExperimentTrialProtocolIdentity:
    selected = require_embodied_videoagent_benchmark(benchmark, split_id=split_id)
    return ExperimentTrialProtocolIdentity(
        "embodied-videoagent.2025.paper-protocol.v1",
        canonical_digest({
            "paper_uri": EMBODIED_VIDEOAGENT_FIDELITY.paper_uri,
            "method_program_digest": EMBODIED_VIDEOAGENT_METHOD_PROGRAM.program_digest,
            "benchmark_id": benchmark.benchmark_id,
            "benchmark_cut_digest": benchmark.cut_digest,
            "split_id": split_id,
            "task_ids": tuple(row.task_id for row in selected),
            "phase_ids": EMBODIED_VIDEOAGENT_FIDELITY.phase_ids,
        }),
    )

def build_embodied_videoagent_study(benchmark: BenchmarkTaskSet, *, split_id: str) -> ResearchStudyDefinition:
    trial = embodied_videoagent_trial_protocol(benchmark, split_id=split_id)
    return Study(
        project_id="embodied-videoagent-2025-reproduction",
        study_id=f"embodied-videoagent-2025-{benchmark.benchmark_id}-{split_id}",
        benchmark=benchmark,
        benchmark_split_id=split_id,
        method=StudyParticipant(
            role="embodied-videoagent_agent",
            kind="agent_method",
            implementation="embodied-videoagent",
            treatment="iccv-2025-paper-protocol",
            capabilities=("model.generate",),
            configurations=EMBODIED_VIDEOAGENT_FIDELITY.phase_ids,
        ),
        models={"controller": StudyModel("model.embodied-videoagent.paper-era", prompt="embodied-videoagent.paper-protocol")},
        measurements=(
            MeasurementDefinition.scalar("task_success", schema_id="noetrium.measurement.ratio.v1", unit="ratio", semantic_kind="task_success", scale="continuous", domain=benchmark.benchmark_id),
            MeasurementDefinition.scalar("agent_phase_count", schema_id="noetrium.measurement.count.v1", unit="phase", semantic_kind="agent_phase_count", scale="count", domain="embodied-videoagent"),
        ),
        trial=trial,
        repetitions=1,
        seeds=("paper-protocol",),
        limits=TrialBudget("embodied-videoagent-2025-budget", max_steps=256, max_turns=128, max_model_calls=128, max_working_seconds=3600.0),
        replay_level=ReplayLevel.OBSERVATIONAL,
        repetition_timeout_seconds=3600.0,
    ).build()

__all__ = ["build_embodied_videoagent_study", "embodied_videoagent_trial_protocol"]
