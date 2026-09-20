from __future__ import annotations

from research.reproductions.frontier_2026.study import PaperStudySpec

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

build_study = SPEC.study
build_ablation_matrix = SPEC.ablation_matrix

__all__ = ["SPEC", "build_ablation_matrix", "build_study"]
