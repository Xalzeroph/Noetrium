from __future__ import annotations
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.lifecycle.api import ExperimentTrialProtocolIdentity
from noetrium_platform.research.experimentation.lifecycle.api import (
    BenchmarkTaskSet, MeasurementDefinition, ReplayLevel, ResearchStudyDefinition,
    Study, StudyModel, StudyParticipant, TrialBudget,
)
from .benchmark import require_watch_and_learn_benchmark
from .fidelity import WATCH_AND_LEARN_FIDELITY
from .program import WATCH_AND_LEARN_METHOD_PROGRAM

def watch_and_learn_trial_protocol(benchmark: BenchmarkTaskSet, *, split_id: str) -> ExperimentTrialProtocolIdentity:
    selected = require_watch_and_learn_benchmark(benchmark, split_id=split_id)
    return ExperimentTrialProtocolIdentity(
        "watch-and-learn.2026.paper-protocol.v1",
        canonical_digest({
            "paper_uri": WATCH_AND_LEARN_FIDELITY.paper_uri,
            "method_program_digest": WATCH_AND_LEARN_METHOD_PROGRAM.program_digest,
            "benchmark_id": benchmark.benchmark_id,
            "benchmark_cut_digest": benchmark.cut_digest,
            "split_id": split_id,
            "task_ids": tuple(row.task_id for row in selected),
            "phase_ids": WATCH_AND_LEARN_FIDELITY.phase_ids,
        }),
    )

def build_watch_and_learn_study(benchmark: BenchmarkTaskSet, *, split_id: str) -> ResearchStudyDefinition:
    trial = watch_and_learn_trial_protocol(benchmark, split_id=split_id)
    return Study(
        project_id="watch-and-learn-2026-reproduction",
        study_id=f"watch-and-learn-2026-{benchmark.benchmark_id}-{split_id}",
        benchmark=benchmark,
        benchmark_split_id=split_id,
        method=StudyParticipant(
            role="watch-and-learn_agent",
            kind="agent_method",
            implementation="watch-and-learn",
            treatment="cvpr-2026-paper-protocol",
            capabilities=("model.generate",),
            configurations=WATCH_AND_LEARN_FIDELITY.phase_ids,
        ),
        models={"controller": StudyModel("model.watch-and-learn.paper-era", prompt="watch-and-learn.paper-protocol")},
        measurements=(
            MeasurementDefinition.scalar("task_success", schema_id="noetrium.measurement.ratio.v1", unit="ratio", semantic_kind="task_success", scale="continuous", domain=benchmark.benchmark_id),
            MeasurementDefinition.scalar("agent_phase_count", schema_id="noetrium.measurement.count.v1", unit="phase", semantic_kind="agent_phase_count", scale="count", domain="watch-and-learn"),
        ),
        trial=trial,
        repetitions=1,
        seeds=("paper-protocol",),
        limits=TrialBudget("watch-and-learn-2026-budget", max_steps=256, max_turns=128, max_model_calls=128, max_working_seconds=3600.0),
        replay_level=ReplayLevel.OBSERVATIONAL,
        repetition_timeout_seconds=3600.0,
    ).build()

__all__ = ["build_watch_and_learn_study", "watch_and_learn_trial_protocol"]
