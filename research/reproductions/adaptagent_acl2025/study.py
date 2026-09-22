from __future__ import annotations
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.lifecycle.api import ExperimentTrialProtocolIdentity
from noetrium_platform.research.experimentation.lifecycle.api import (
    BenchmarkTaskSet, MeasurementDefinition, ReplayLevel, ResearchStudyDefinition,
    Study, StudyModel, StudyParticipant, TrialBudget,
)
from .benchmark import require_adaptagent_benchmark
from .fidelity import ADAPTAGENT_FIDELITY
from .program import ADAPTAGENT_METHOD_PROGRAM

def adaptagent_trial_protocol(benchmark: BenchmarkTaskSet, *, split_id: str) -> ExperimentTrialProtocolIdentity:
    selected = require_adaptagent_benchmark(benchmark, split_id=split_id)
    return ExperimentTrialProtocolIdentity(
        "adaptagent.2025.paper-protocol.v1",
        canonical_digest({
            "paper_uri": ADAPTAGENT_FIDELITY.paper_uri,
            "method_program_digest": ADAPTAGENT_METHOD_PROGRAM.program_digest,
            "benchmark_id": benchmark.benchmark_id,
            "benchmark_cut_digest": benchmark.cut_digest,
            "split_id": split_id,
            "task_ids": tuple(row.task_id for row in selected),
            "phase_ids": ADAPTAGENT_FIDELITY.phase_ids,
        }),
    )

def build_adaptagent_study(benchmark: BenchmarkTaskSet, *, split_id: str) -> ResearchStudyDefinition:
    trial = adaptagent_trial_protocol(benchmark, split_id=split_id)
    return Study(
        project_id="adaptagent-2025-reproduction",
        study_id=f"adaptagent-2025-{benchmark.benchmark_id}-{split_id}",
        benchmark=benchmark,
        benchmark_split_id=split_id,
        method=StudyParticipant(
            role="adaptagent_agent",
            kind="agent_method",
            implementation="adaptagent",
            treatment="acl-2025-paper-protocol",
            capabilities=("model.generate",),
            configurations=ADAPTAGENT_FIDELITY.phase_ids,
        ),
        models={"controller": StudyModel("model.adaptagent.paper-era", prompt="adaptagent.paper-protocol")},
        measurements=(
            MeasurementDefinition.scalar("task_success", schema_id="noetrium.measurement.ratio.v1", unit="ratio", semantic_kind="task_success", scale="continuous", domain=benchmark.benchmark_id),
            MeasurementDefinition.scalar("agent_phase_count", schema_id="noetrium.measurement.count.v1", unit="phase", semantic_kind="agent_phase_count", scale="count", domain="adaptagent"),
        ),
        trial=trial,
        repetitions=1,
        seeds=("paper-protocol",),
        limits=TrialBudget("adaptagent-2025-budget", max_steps=256, max_turns=128, max_model_calls=128, max_working_seconds=3600.0),
        replay_level=ReplayLevel.OBSERVATIONAL,
        repetition_timeout_seconds=3600.0,
    ).build()

__all__ = ["build_adaptagent_study", "adaptagent_trial_protocol"]
