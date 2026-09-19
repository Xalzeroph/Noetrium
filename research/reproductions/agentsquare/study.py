from __future__ import annotations

from collections.abc import Mapping

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

from .fidelity import AGENTSQUARE_FIDELITY
from .reported import (
    AGENTSQUARE_BENCHMARK_PROFILE_BY_ID,
    AgentSquareBenchmarkProfile,
    AgentSquareTreatment,
)


def _profile_for(benchmark: BenchmarkTaskSet) -> AgentSquareBenchmarkProfile:
    if not isinstance(benchmark, BenchmarkTaskSet):
        raise TypeError("AgentSquare study requires BenchmarkTaskSet")
    try:
        profile = AGENTSQUARE_BENCHMARK_PROFILE_BY_ID[benchmark.benchmark_id]
    except KeyError as exc:
        raise ValueError(
            "benchmark is outside the AgentSquare six-benchmark protocol"
        ) from exc
    if benchmark.revision_id != profile.revision_id:
        raise ValueError(
            "AgentSquare benchmark revision does not match frozen protocol"
        )
    benchmark.selected_tasks(profile.evaluation_split_id)
    return profile


def _measurement_definitions(
    profile: AgentSquareBenchmarkProfile,
) -> tuple[MeasurementDefinition, ...]:
    return (
        MeasurementDefinition.scalar(
            profile.primary_measurement_id,
            schema_id="noetrium.measurement.scalar.v1",
            unit=profile.primary_unit,
            semantic_kind=profile.primary_semantic_kind,
            scale=profile.primary_scale,
            domain=profile.domain,
        ),
        MeasurementDefinition.scalar(
            "api_cost_usd",
            schema_id="noetrium.measurement.scalar.v1",
            unit="usd",
            semantic_kind="api_cost",
            scale="ratio",
            domain="agentsquare",
        ),
        MeasurementDefinition.scalar(
            "model_call_count",
            schema_id="noetrium.measurement.count.v1",
            unit="model_call",
            semantic_kind="model_usage",
            scale="count",
            domain="agentsquare",
        ),
        MeasurementDefinition.scalar(
            "prompt_token_count",
            schema_id="noetrium.measurement.count.v1",
            unit="token",
            semantic_kind="prompt_token_usage",
            scale="count",
            domain="agentsquare",
        ),
        MeasurementDefinition.scalar(
            "completion_token_count",
            schema_id="noetrium.measurement.count.v1",
            unit="token",
            semantic_kind="completion_token_usage",
            scale="count",
            domain="agentsquare",
        ),
    )


def agentsquare_trial_protocol(
    profile: AgentSquareBenchmarkProfile,
    treatment: AgentSquareTreatment,
) -> ExperimentTrialProtocolIdentity:
    if not isinstance(profile, AgentSquareBenchmarkProfile):
        raise TypeError("AgentSquare trial protocol requires benchmark profile")
    if not isinstance(treatment, AgentSquareTreatment):
        raise TypeError("AgentSquare trial protocol requires AgentSquareTreatment")
    return ExperimentTrialProtocolIdentity(
        f"agentsquare.iclr2025.{profile.key}.{treatment.value}.gpt4o.v1",
        canonical_digest(
            {
                "paper": "AgentSquare ICLR 2025",
                "paper_model_family": "GPT-4o",
                "seed_schedule_published": False,
                "benchmark_id": profile.benchmark_id,
                "benchmark_revision": profile.revision_id,
                "evaluation_split_id": profile.evaluation_split_id,
                "treatment": treatment.value,
                "four_module_design_space": AGENTSQUARE_FIDELITY.module_types,
                "mechanisms": AGENTSQUARE_FIDELITY.mechanisms,
                "source_commit": AGENTSQUARE_FIDELITY.audited_commit,
                "final_agent_binding": (
                    f"agentsquare.final-agent.{profile.key}.{treatment.value}"
                ),
            }
        ),
    )


def build_agentsquare_evaluation_study(
    benchmark: BenchmarkTaskSet,
    *,
    treatment: AgentSquareTreatment = AgentSquareTreatment.FULL,
    max_parallel_assignments: int = 16,
) -> ResearchStudyDefinition:
    """Build one paper evaluation treatment over one frozen benchmark cut.

    The study evaluates a searched final-agent artifact. It does not rerun the
    architecture search once per benchmark task. Search and final evaluation are
    separate scientific phases and must be linked by the final-agent artifact
    lineage when executed on the server.
    """

    if not isinstance(treatment, AgentSquareTreatment):
        raise TypeError("AgentSquare treatment must be AgentSquareTreatment")
    if type(max_parallel_assignments) is not int or max_parallel_assignments <= 0:
        raise ValueError("max_parallel_assignments must be positive")

    profile = _profile_for(benchmark)
    artifact_requirement = (
        f"agentsquare.final-agent.{profile.key}.{treatment.value}"
    )
    study_id = f"agentsquare-{profile.key}-{treatment.value}-gpt4o"
    return Study(
        project_id="agentsquare-iclr2025-reproduction",
        study_id=study_id,
        benchmark=benchmark,
        benchmark_split_id=profile.evaluation_split_id,
        method=StudyParticipant(
            role="agent",
            kind="searched_modular_agent",
            implementation="agentsquare",
            treatment=treatment.value,
            configurations=(
                "agentsquare.iclr2025.modular-design-space",
                artifact_requirement,
            ),
        ),
        models={
            "module_llm": StudyModel(
                "model.agentsquare.gpt-4o",
                required=True,
                max_bindings=1,
            ),
        },
        measurements=_measurement_definitions(profile),
        trial=agentsquare_trial_protocol(profile, treatment),
        repetitions=1,
        seeds=("paper-seed-unpublished",),
        limits=TrialBudget(
            f"agentsquare-{profile.key}-evaluation-safety-cap",
            max_steps=4096,
            max_model_calls=4096,
            max_working_seconds=14400.0,
        ),
        replay_level=ReplayLevel.OBSERVATIONAL,
        concurrency_policy=StudyConcurrencyPolicy.isolated_parallel_v1(
            max_parallel_repetitions=1,
            max_parallel_assignments=max_parallel_assignments,
            repetition_timeout_seconds=14400.0,
        ),
    ).build()


def build_agentsquare_ablation_matrix(
    benchmarks: Mapping[str, BenchmarkTaskSet],
    *,
    max_parallel_assignments: int = 16,
) -> tuple[ResearchStudyDefinition, ...]:
    """Compile the 6 benchmarks × 3 paper treatments into 18 studies."""

    if not isinstance(benchmarks, Mapping):
        raise TypeError("AgentSquare benchmark matrix must be a mapping")
    expected = set(AGENTSQUARE_BENCHMARK_PROFILE_BY_ID)
    if set(benchmarks) != expected:
        missing = tuple(sorted(expected - set(benchmarks)))
        extra = tuple(sorted(set(benchmarks) - expected))
        raise ValueError(
            "AgentSquare benchmark matrix must contain exactly six benchmarks "
            f"(missing={missing}, extra={extra})"
        )

    rows: list[ResearchStudyDefinition] = []
    for benchmark_id in sorted(expected):
        benchmark = benchmarks[benchmark_id]
        if benchmark.benchmark_id != benchmark_id:
            raise ValueError("AgentSquare benchmark mapping key drifted")
        for treatment in AgentSquareTreatment:
            rows.append(
                build_agentsquare_evaluation_study(
                    benchmark,
                    treatment=treatment,
                    max_parallel_assignments=max_parallel_assignments,
                )
            )
    return tuple(rows)


__all__ = [
    "agentsquare_trial_protocol",
    "build_agentsquare_ablation_matrix",
    "build_agentsquare_evaluation_study",
]
