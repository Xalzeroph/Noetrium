from __future__ import annotations
from research.reproductions import _support as _rs

from collections.abc import Mapping

from .fidelity import AGENTSQUARE_FIDELITY
from .reported import (
    AGENTSQUARE_BENCHMARK_PROFILE_BY_ID,
    AgentSquareBenchmarkProfile,
    AgentSquareTreatment,
)


def _profile_for(benchmark) -> AgentSquareBenchmarkProfile:
    if not hasattr(benchmark, "benchmark_id") or not callable(getattr(benchmark, "selected_tasks", None)):
        raise TypeError("AgentSquare study requires a resolved benchmark")
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
    selected = benchmark.selected_tasks(profile.evaluation_split_id)
    if len(selected) != profile.expected_evaluation_task_count:
        raise ValueError(
            "AgentSquare benchmark cut task cardinality does not match "
            "the frozen paper evaluation protocol"
        )
    return profile


def _measurement_definitions(
    profile: AgentSquareBenchmarkProfile,
):
    return (
        _rs.scalar_measurement(
            profile.primary_measurement_id,
            schema_id="noetrium.measurement.scalar.v1",
            unit=profile.primary_unit,
            semantic_kind=profile.primary_semantic_kind,
            scale=profile.primary_scale,
            domain=profile.domain,
        ),
        _rs.scalar_measurement(
            "api_cost_usd",
            schema_id="noetrium.measurement.scalar.v1",
            unit="usd",
            semantic_kind="api_cost",
            scale="ratio",
            domain="agentsquare",
        ),
        _rs.scalar_measurement(
            "model_call_count",
            schema_id="noetrium.measurement.count.v1",
            unit="model_call",
            semantic_kind="model_usage",
            scale="count",
            domain="agentsquare",
        ),
        _rs.scalar_measurement(
            "prompt_token_count",
            schema_id="noetrium.measurement.count.v1",
            unit="token",
            semantic_kind="prompt_token_usage",
            scale="count",
            domain="agentsquare",
        ),
        _rs.scalar_measurement(
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
):
    if not isinstance(profile, AgentSquareBenchmarkProfile):
        raise TypeError("AgentSquare trial protocol requires benchmark profile")
    if not isinstance(treatment, AgentSquareTreatment):
        raise TypeError("AgentSquare trial protocol requires AgentSquareTreatment")
    return _rs.study_protocol(
        f"agentsquare.iclr2025.{profile.key}.{treatment.value}.gpt4o.v1",
        _rs.canonical_digest(
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


@_rs.study_factory('benchmark')
def build_agentsquare_evaluation_study(
    benchmark,
    *,
    treatment: AgentSquareTreatment = AgentSquareTreatment.FULL,
    max_parallel_assignments: int = 16,
):
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
    return _rs.study_spec(project_id="agentsquare-iclr2025-reproduction",
        study_id=study_id,
        benchmark=benchmark,
        benchmark_split_id=profile.evaluation_split_id,
        method=_rs.study_participant(
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
            "module_llm": _rs.study_model(
                "model.agentsquare.gpt-4o",
                required=True,
                max_bindings=1,
            ),
        },
        measurements=_measurement_definitions(profile),
        trial=agentsquare_trial_protocol(profile, treatment),
        repetitions=1,
        seeds=("paper-seed-unpublished",),
        limits=_rs.trial_budget(
            f"agentsquare-{profile.key}-evaluation-safety-cap",
            max_steps=4096,
            max_model_calls=4096,
            max_working_seconds=14400.0,
        ),
        replay_level='observational',
        concurrency_policy=_rs.study_concurrency_isolated(
            max_parallel_repetitions=1,
            max_parallel_assignments=max_parallel_assignments,
            repetition_timeout_seconds=14400.0,
        ),
    )


for _benchmark_profile in sorted(
    AGENTSQUARE_BENCHMARK_PROFILE_BY_ID.values(),
    key=lambda row: row.benchmark_id,
):
    build_agentsquare_evaluation_study = _rs.requires_benchmark_cut(build_agentsquare_evaluation_study)
del _benchmark_profile


@_rs.study_factory('benchmarks')
def build_agentsquare_ablation_matrix(
    benchmarks,
    *,
    max_parallel_assignments: int = 16,
):
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

    rows: list[dict[str, object]] = []
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
