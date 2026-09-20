"""Low-friction Study compiler for source-bound paper reproductions.

Each reproduction owns its local PaperStudySpec. Study compilation is
registry-independent and never resolves a method through a central wave table.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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


@dataclass(frozen=True, slots=True)
class PaperStudySpec:
    method_id: str
    title: str
    venue: str
    paper_uri: str
    benchmark_ids: tuple[str, ...]
    protocol: tuple[str, ...]
    metrics: tuple[str, ...]
    ablations: tuple[str, ...]
    scientific_digest: str | None = None
    spec_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name, value in (
            ("method_id", self.method_id),
            ("title", self.title),
            ("venue", self.venue),
            ("paper_uri", self.paper_uri),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"paper study {name} must be non-empty text")
        if not self.paper_uri.startswith("https://"):
            raise ValueError("paper study paper_uri must be HTTPS")
        for name in ("benchmark_ids", "protocol", "metrics", "ablations"):
            value = getattr(self, name)
            if type(value) is not tuple or not value:
                raise ValueError(f"paper study {name} must be a non-empty tuple")
            if any(type(row) is not str or not row.strip() for row in value):
                raise TypeError(f"paper study {name} must contain non-empty text")
            if len(value) != len(set(value)):
                raise ValueError(f"paper study {name} must be unique")
        digest = self.scientific_digest
        if digest is not None and (
            type(digest) is not str
            or len(digest) != 64
            or any(ch not in "0123456789abcdef" for ch in digest)
        ):
            raise ValueError("paper study scientific_digest must be lowercase SHA-256")
        object.__setattr__(
            self,
            "spec_digest",
            canonical_digest(
                {
                    "method_id": self.method_id,
                    "title": self.title,
                    "venue": self.venue,
                    "paper_uri": self.paper_uri,
                    "benchmark_ids": self.benchmark_ids,
                    "protocol": self.protocol,
                    "metrics": self.metrics,
                    "ablations": self.ablations,
                    "scientific_digest": digest,
                }
            ),
        )


def _measurement(metric: str, *, domain: str) -> MeasurementDefinition:
    normalized = metric.lower()
    if (
        normalized in {
            "steps",
            "model_calls",
            "memory_action_count",
            "imagined_rollouts",
            "tutorial_search_count",
            "memory_corrections",
            "visual_focus_operations",
            "platform_count",
        }
        or normalized.endswith("_count")
        or normalized.endswith("_operations")
        or normalized.endswith("_steps")
    ):
        return MeasurementDefinition.scalar(
            metric,
            schema_id="noetrium.measurement.count.v1",
            unit="count",
            semantic_kind=metric,
            scale="count",
            domain=domain,
        )
    if "token" in normalized:
        return MeasurementDefinition.scalar(
            metric,
            schema_id="noetrium.measurement.count.v1",
            unit="token",
            semantic_kind=metric,
            scale="count",
            domain=domain,
        )
    if "latency" in normalized or normalized.endswith("_seconds"):
        return MeasurementDefinition.scalar(
            metric,
            schema_id="noetrium.measurement.scalar.v1",
            unit="second",
            semantic_kind=metric,
            scale="ratio",
            domain=domain,
        )
    if "cost" in normalized:
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


def trial_protocol_from_spec(
    spec: PaperStudySpec,
    benchmark: BenchmarkTaskSet,
    *,
    benchmark_split_id: str,
    treatment: str,
    model_binding: str,
) -> ExperimentTrialProtocolIdentity:
    if not isinstance(spec, PaperStudySpec):
        raise TypeError("trial protocol requires PaperStudySpec")
    return ExperimentTrialProtocolIdentity(
        f"{spec.method_id}.{benchmark.benchmark_id}.{treatment}.v1",
        canonical_digest(
            {
                "paper": spec.title,
                "venue": spec.venue,
                "paper_uri": spec.paper_uri,
                "paper_spec_digest": spec.spec_digest,
                "scientific_digest": spec.scientific_digest,
                "benchmark_id": benchmark.benchmark_id,
                "benchmark_revision": benchmark.revision_id,
                "benchmark_split_id": benchmark_split_id,
                "treatment": treatment,
                "model_binding": model_binding,
                "protocol": spec.protocol,
                "ablations": spec.ablations,
            }
        ),
    )


def build_study_from_spec(
    spec: PaperStudySpec,
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
    """Compile one paper-local protocol into the canonical Study authority."""

    if not isinstance(spec, PaperStudySpec):
        raise TypeError("study compiler requires PaperStudySpec")
    if not isinstance(benchmark, BenchmarkTaskSet):
        raise TypeError("paper study requires BenchmarkTaskSet")
    if type(benchmark_split_id) is not str or not benchmark_split_id.strip():
        raise ValueError("benchmark_split_id must be non-empty")
    if type(treatment) is not str or not treatment.strip():
        raise ValueError("treatment must be non-empty")
    valid_treatments = ("full",) + tuple(
        "ablation:" + row for row in spec.ablations
    )
    if treatment not in valid_treatments:
        raise ValueError(
            f"unsupported {spec.method_id} treatment {treatment!r}; "
            f"expected one of {valid_treatments!r}"
        )
    if type(repetitions) is not int or repetitions < 1:
        raise ValueError("repetitions must be positive")
    if type(max_parallel_assignments) is not int or max_parallel_assignments < 1:
        raise ValueError("max_parallel_assignments must be positive")
    if benchmark.benchmark_id not in spec.benchmark_ids:
        raise ValueError(
            f"{benchmark.benchmark_id!r} is outside {spec.method_id} paper protocol; "
            f"expected one of {tuple(sorted(spec.benchmark_ids))!r}"
        )

    selected = benchmark.selected_tasks(benchmark_split_id)
    if not selected:
        raise ValueError("selected benchmark split cannot be empty")

    protocol = trial_protocol_from_spec(
        spec,
        benchmark,
        benchmark_split_id=benchmark_split_id,
        treatment=treatment,
        model_binding=model_binding,
    )
    return Study(
        project_id=f"{spec.method_id}-reproduction",
        study_id=(
            f"{spec.method_id}-{benchmark.benchmark_id}-"
            f"{treatment.replace(':', '-')}"
        ),
        benchmark=benchmark,
        benchmark_split_id=benchmark_split_id,
        method=StudyParticipant(
            role="agent",
            kind="paper_method_program",
            implementation=spec.method_id,
            treatment=treatment,
            configurations=(
                f"paper-program.{spec.method_id}",
                f"paper-study-spec.{spec.spec_digest}",
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
            _measurement(metric, domain=spec.method_id)
            for metric in spec.metrics
        ),
        trial=protocol,
        repetitions=repetitions,
        seeds=tuple(f"repetition-{index}" for index in range(repetitions)),
        limits=TrialBudget(
            f"{spec.method_id}-paper-evaluation-safety-cap",
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


def build_ablation_matrix_from_spec(
    spec: PaperStudySpec,
    benchmark: BenchmarkTaskSet,
    *,
    benchmark_split_id: str,
    model_binding: str = "model.paper-authoritative",
    repetitions: int = 1,
) -> tuple[ResearchStudyDefinition, ...]:
    treatments = ("full",) + tuple(
        "ablation:" + row for row in spec.ablations
    )
    return tuple(
        build_study_from_spec(
            spec,
            benchmark,
            benchmark_split_id=benchmark_split_id,
            treatment=treatment,
            model_binding=model_binding,
            repetitions=repetitions,
        )
        for treatment in treatments
    )



__all__ = [
    "PaperStudySpec",
    "build_ablation_matrix_from_spec",
    "build_study_from_spec",
    "trial_protocol_from_spec",
]
