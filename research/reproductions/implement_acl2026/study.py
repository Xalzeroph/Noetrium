from __future__ import annotations

from noetrium_platform.research.experimentation.lifecycle.api import BenchmarkTaskSet, ResearchStudyDefinition
from research.authoring.frontier_2026.study import (
    PaperStudySpec,
    build_ablation_matrix_from_spec,
    build_study_from_spec,
)
from .benchmark import require_paper_benchmark
from .program import ABLATIONS, BENCHMARK_IDS, METHOD_ID, METRICS, PAPER_URI, PROTOCOL

SPEC = PaperStudySpec(
    method_id=METHOD_ID,
    title="Model-Based Imaginative Planning for Embodied Agents",
    venue="ACL 2026",
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
) -> ResearchStudyDefinition:
    require_paper_benchmark(benchmark.benchmark_id)
    return build_study_from_spec(
        SPEC,
        benchmark,
        benchmark_split_id=benchmark_split_id,
        treatment=treatment,
        model_binding=model_binding,
        repetitions=repetitions,
    )


def build_ablation_matrix(
    benchmark: BenchmarkTaskSet,
    *,
    benchmark_split_id: str,
    model_binding: str = "model.paper-authoritative",
    repetitions: int = 1,
) -> tuple[ResearchStudyDefinition, ...]:
    require_paper_benchmark(benchmark.benchmark_id)
    return build_ablation_matrix_from_spec(
        SPEC,
        benchmark,
        benchmark_split_id=benchmark_split_id,
        model_binding=model_binding,
        repetitions=repetitions,
    )


__all__ = ["SPEC", "build_ablation_matrix", "build_study"]
