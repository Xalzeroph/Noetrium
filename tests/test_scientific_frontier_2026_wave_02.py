from __future__ import annotations

from research.reproductions.frontier_2026.study import PaperStudySpec


def test_paper_study_spec_is_registry_independent() -> None:
    spec = PaperStudySpec(
        method_id="frontier-wave-02-smoke",
        title="Frontier Wave 02 Smoke",
        venue="CVPR 2026",
        paper_uri="https://example.org/frontier-wave-02-smoke",
        benchmark_ids=("benchmark-a",),
        protocol=("freeze paper protocol",),
        metrics=("task_success",),
        ablations=("without component",),
    )
    assert spec.method_id == "frontier-wave-02-smoke"
    assert len(spec.spec_digest) == 64
