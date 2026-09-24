from __future__ import annotations

from noetrium_platform.research.experimentation.lifecycle.api import (
    BenchmarkTaskSet,
    ResearchStudyDefinition,
)
from research.authoring.frontier_2026.study import PaperStudySpec

from .program import (
    ABLATIONS,
    BENCHMARK_IDS,
    METHOD_ID,
    METRICS,
    PAPER_URI,
    PROTOCOL,
    TITLE,
    VENUE,
)

SPEC = PaperStudySpec(
    method_id=METHOD_ID,
    title=TITLE,
    venue=VENUE,
    paper_uri=PAPER_URI,
    benchmark_ids=BENCHMARK_IDS,
    protocol=PROTOCOL,
    metrics=METRICS,
    ablations=ABLATIONS,
)


def build_study(
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
    """Compile this paper's protocol through the canonical Study authority."""

    return SPEC.study(
        benchmark,
        benchmark_split_id=benchmark_split_id,
        treatment=treatment,
        model_binding=model_binding,
        repetitions=repetitions,
        max_parallel_assignments=max_parallel_assignments,
        max_steps=max_steps,
        max_model_calls=max_model_calls,
        max_working_seconds=max_working_seconds,
    )


def build_ablation_matrix(
    benchmark: BenchmarkTaskSet,
    *,
    benchmark_split_id: str,
    model_binding: str = "model.paper-authoritative",
    repetitions: int = 1,
) -> tuple[ResearchStudyDefinition, ...]:
    return SPEC.ablation_matrix(
        benchmark,
        benchmark_split_id=benchmark_split_id,
        model_binding=model_binding,
        repetitions=repetitions,
    )


__all__ = ["SPEC", "build_ablation_matrix", "build_study"]
