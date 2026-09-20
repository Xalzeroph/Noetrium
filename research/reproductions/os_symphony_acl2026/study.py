from __future__ import annotations

from noetrium_platform.research.experimentation.study.api import BenchmarkTaskSet, ResearchStudyDefinition
from research.reproductions.frontier_2026.study import (
    build_ablation_matrix as _build_ablation_matrix,
    build_study as _build_study,
)
from .benchmark import require_paper_benchmark
from .program import METHOD_ID


def build_study(
    benchmark: BenchmarkTaskSet,
    *,
    benchmark_split_id: str,
    treatment: str = "full",
    model_binding: str = "model.paper-authoritative",
    repetitions: int = 1,
) -> ResearchStudyDefinition:
    require_paper_benchmark(benchmark.benchmark_id)
    return _build_study(
        METHOD_ID,
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
    return _build_ablation_matrix(
        METHOD_ID,
        benchmark,
        benchmark_split_id=benchmark_split_id,
        model_binding=model_binding,
        repetitions=repetitions,
    )


__all__ = ["build_ablation_matrix", "build_study"]
