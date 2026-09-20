"""Study compiler for the 2026 frontier reproduction implementations."""

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
    StudyConcurrencyPolicy,
    StudyModel,
    StudyParticipant,
    TrialBudget,
)

from .wave_01 import Frontier2026Reproduction, by_id


def _measurement(metric: str, *, domain: str) -> MeasurementDefinition:
    if metric in {"steps", "model_calls", "memory_action_count", "imagined_rollouts", "tutorial_search_count", "memory_corrections", "visual_focus_operations"}:
        return MeasurementDefinition.scalar(
            metric,
            schema_id="noetrium.measurement.count.v1",
            unit="count",
            semantic_kind=metric,
            scale="count",
            domain=domain,
        )
    if "token" in metric:
        return MeasurementDefinition.scalar(
            metric,
            schema_id="noetrium.measurement.count.v1",
            unit="token",
            semantic_kind=metric,
            scale="count",
            domain=domain,
        )
    if "latency" in metric:
        return MeasurementDefinition.scalar(
            metric,
            schema_id="noetrium.measurement.scalar.v1",
            unit="second",
            semantic_kind=metric,
            scale="ratio",
            domain=domain,
        )
    if "cost" in metric:
        return MeasurementDefinition.scalar(
            metric,
            schema_id="noetrium.measurement.scalar.v1",
            unit="cost",
            semantic_kind=metric,
            scale="ratio",
            domain=domain,
        )
    return MeasurementDefinition.scalar(
        metric,
        schema_id="noetrium.measurement.scalar.v1",
        unit="score",
        semantic_kind=metric,
        scale="continuous",
        domain=domain,
    )


def trial_protocol(
    reproduction: Frontier2026Reproduction,
    benchmark: BenchmarkTaskSet,
    *,
    benchmark_split_id: str,
    treatment: str,
    model_binding: str,
) -> ExperimentTrialProtocolIdentity:
    return ExperimentTrialProtocolIdentity(
        f"{reproduction.method_id}.{benchmark.benchmark_id}.{treatment}.v1",
        canonical_digest(
            {
                "paper": reproduction.title,
                "venue": reproduction.venue,
                "paper_uri": reproduction.paper_uri,
                "reproduction_digest": reproduction.reproduction_digest,
                "benchmark_id": benchmark.benchmark_id,
                "benchmark_revision": benchmark.revision_id,
                "benchmark_split_id": benchmark_split_id,
                "treatment": treatment,
                "model_binding": model_binding,
                "protocol": reproduction.protocol,
                "ablations": reproduction.ablations,
            }
        ),
    )


def build_study(
    method_id: str,
    benchmark: BenchmarkTaskSet,
    *,
    benchmark_split_id: str,
    treatment: str = "full",
    model_binding: str = "model.paper-authoritative",
    repetitions: int = 1,
    max_parallel_assignments: int = 8,
    max_steps: int = 4096,
    max_model_calls: int = 4096,
    max_working_seconds: float = 14400.0,
) -> ResearchStudyDefinition:
    """Compile one frozen benchmark/treatment into the normal Study authority.

    The benchmark adapter owns dataset/environment materialization.  This compiler
    owns only the paper experiment protocol.  The caller must supply the exact
    source-bound BenchmarkTaskSet and split, preventing hidden benchmark drift.
    """

    reproduction = by_id(method_id)
    if not isinstance(benchmark, BenchmarkTaskSet):
        raise TypeError("frontier 2026 study requires BenchmarkTaskSet")
    if type(benchmark_split_id) is not str or not benchmark_split_id.strip():
        raise ValueError("benchmark_split_id must be non-empty")
    if type(treatment) is not str or not treatment.strip():
        raise ValueError("treatment must be non-empty")
    valid_treatments = ("full",) + tuple(
        "ablation:" + row for row in reproduction.ablations
    )
    if treatment not in valid_treatments:
        raise ValueError(
            f"unsupported {method_id} treatment {treatment!r}; "
            f"expected one of {valid_treatments!r}"
        )
    if type(repetitions) is not int or repetitions < 1:
        raise ValueError("repetitions must be positive")
    if type(max_parallel_assignments) is not int or max_parallel_assignments < 1:
        raise ValueError("max_parallel_assignments must be positive")

    binding_ids = {row.benchmark_id for row in reproduction.benchmarks}
    if benchmark.benchmark_id not in binding_ids:
        raise ValueError(
            f"{benchmark.benchmark_id!r} is outside {method_id} paper protocol; "
            f"expected one of {tuple(sorted(binding_ids))!r}"
        )

    selected = benchmark.selected_tasks(benchmark_split_id)
    if not selected:
        raise ValueError("selected benchmark split cannot be empty")

    protocol = trial_protocol(
        reproduction,
        benchmark,
        benchmark_split_id=benchmark_split_id,
        treatment=treatment,
        model_binding=model_binding,
    )
    return Study(
        project_id=f"{method_id}-reproduction",
        study_id=f"{method_id}-{benchmark.benchmark_id}-{treatment.replace(':', '-')}",
        benchmark=benchmark,
        benchmark_split_id=benchmark_split_id,
        method=StudyParticipant(
            role="agent",
            kind="paper_method_program",
            implementation=method_id,
            treatment=treatment,
            configurations=(
                f"frontier2026.program.{method_id}",
                f"frontier2026.reproduction.{reproduction.reproduction_digest}",
            ),
        ),
        models={
            "agent_model": StudyModel(
                model_binding,
                required=True,
                max_bindings=1,
            ),
        },
        measurements=tuple(
            _measurement(metric, domain=method_id)
            for metric in reproduction.metrics
        ),
        trial=protocol,
        repetitions=repetitions,
        seeds=tuple(f"repetition-{index}" for index in range(repetitions)),
        limits=TrialBudget(
            f"{method_id}-paper-evaluation-safety-cap",
            max_steps=max_steps,
            max_model_calls=max_model_calls,
            max_working_seconds=max_working_seconds,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
        concurrency_policy=StudyConcurrencyPolicy.isolated_parallel_v1(
            max_parallel_repetitions=1,
            max_parallel_assignments=max_parallel_assignments,
            repetition_timeout_seconds=max_working_seconds,
        ),
    ).build()


def build_ablation_matrix(
    method_id: str,
    benchmark: BenchmarkTaskSet,
    *,
    benchmark_split_id: str,
    model_binding: str = "model.paper-authoritative",
    repetitions: int = 1,
) -> tuple[ResearchStudyDefinition, ...]:
    reproduction = by_id(method_id)
    treatments = ("full",) + tuple(
        "ablation:" + row for row in reproduction.ablations
    )
    return tuple(
        build_study(
            method_id,
            benchmark,
            benchmark_split_id=benchmark_split_id,
            treatment=treatment,
            model_binding=model_binding,
            repetitions=repetitions,
        )
        for treatment in treatments
    )


__all__ = [
    "build_ablation_matrix",
    "build_study",
    "trial_protocol",
]
