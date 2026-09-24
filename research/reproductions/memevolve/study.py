from __future__ import annotations

from noetrium.api import canonical_digest
from noetrium.api import (
    BenchmarkTaskSet,
    ExperimentTrialProtocolIdentity,
    MeasurementDefinition,
    ReplayLevel,
    ResearchStudyDefinition,
    Study,
    StudyModel,
    StudyParticipant,
    TrialBudget,
)
from research.benchmarks.memoryarena import MEMORYARENA_BENCHMARK_ID

from .fidelity import MEMEVOLVE_FIDELITY
from .program import MEMEVOLVE_METHOD_PROGRAM


_SUPPORTED_BENCHMARKS = frozenset({MEMORYARENA_BENCHMARK_ID, "evomembench"})


def memevolve_trial_protocol(
    benchmark: BenchmarkTaskSet,
    *,
    split_id: str,
) -> ExperimentTrialProtocolIdentity:
    f = MEMEVOLVE_FIDELITY
    if benchmark.benchmark_id not in _SUPPORTED_BENCHMARKS:
        raise ValueError(
            "MemEvolve study requires MemoryArena or EvoMemBench"
        )
    selected = benchmark.selected_tasks(split_id)
    if not selected:
        raise ValueError("MemEvolve study requires a non-empty benchmark split")
    return ExperimentTrialProtocolIdentity(
        f"memevolve.{benchmark.benchmark_id}.meta-evolution.v1",
        canonical_digest(
            {
                "program_digest": MEMEVOLVE_METHOD_PROGRAM.program_digest,
                "benchmark_id": benchmark.benchmark_id,
                "benchmark_cut_digest": benchmark.cut_digest,
                "split_id": split_id,
                "task_ids": tuple(row.task_id for row in selected),
                "source_commit": f.audited_code_commit,
                "manual_phases": f.manual_phases,
                "round_process": f.round_process,
                "candidate_generation_independent": f.candidate_generation_independent,
                "same_task_tournament_required": f.same_task_tournament_required,
                "winner_becomes_next_round_base": f.winner_becomes_next_round_base,
            }
        ),
    )


def build_memevolve_study(
    benchmark: BenchmarkTaskSet,
    *,
    split_id: str,
) -> ResearchStudyDefinition:
    protocol = memevolve_trial_protocol(
        benchmark,
        split_id=split_id,
    )
    domain = benchmark.benchmark_id
    return Study(
        project_id="memevolve-reproduction",
        study_id=f"memevolve-{domain}-{split_id}",
        benchmark=benchmark,
        benchmark_split_id=split_id,
        method=StudyParticipant(
            role="meta_memory_search",
            kind="memory_meta_evolution",
            implementation="memevolve",
            treatment="dual-content-architecture-evolution",
            capabilities=("workbench.candidate-program.execute",),
            configurations=(
                "memevolve.manual-evolution",
                "memevolve.same-task-tournament",
                "memevolve.extended-task-finals",
            ),
        ),
        models={
            "memevolve.analyzer": StudyModel(
                "model.memevolve.meta",
                prompt="memevolve.analyze-trajectories",
            ),
            "memevolve.memory-generator": StudyModel(
                "model.memevolve.meta",
                prompt="memevolve.generate-memory-system",
            ),
            "memevolve.implementation-generator": StudyModel(
                "model.memevolve.meta",
                prompt="memevolve.create-implementation",
            ),
        },
        measurements=(
            MeasurementDefinition.scalar(
                "memory_score",
                schema_id="noetrium.measurement.scalar.v1",
                unit="score",
                semantic_kind="memory_system_quality",
                scale="continuous",
                domain=domain,
            ),
            MeasurementDefinition.scalar(
                "round_count",
                schema_id="noetrium.measurement.count.v1",
                unit="round",
                semantic_kind="meta_evolution_round_count",
                scale="count",
                domain=domain,
            ),
            MeasurementDefinition.scalar(
                "candidate_execution_count",
                schema_id="noetrium.measurement.count.v1",
                unit="execution",
                semantic_kind="candidate_evaluation_usage",
                scale="count",
                domain=domain,
            ),
        ),
        trial=protocol,
        repetitions=1,
        seeds=("0",),
        limits=TrialBudget(
            "memevolve-host-safety",
            max_steps=8192,
            max_turns=2048,
            max_model_calls=2048,
            max_working_seconds=7200.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
    ).build()


__all__ = [
    "build_memevolve_study",
    "memevolve_trial_protocol",
]
