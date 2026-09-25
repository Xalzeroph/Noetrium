from __future__ import annotations

from research.authoring.frontier_2026.study import PaperStudySpec
from research.reproductions.motus_cvpr2026.program import METHOD_PROGRAM as MOTUS
from research.reproductions.motus_cvpr2026.study import SPEC as MOTUS_SPEC
from research.reproductions.vilomem_cvpr2026.program import METHOD_PROGRAM as VILOMEM
from research.reproductions.vilomem_cvpr2026.study import SPEC as VILOMEM_SPEC


def test_wave_03_memory_and_world_model_programs_compile() -> None:
    assert VILOMEM is not None
    assert MOTUS is not None
    assert isinstance(VILOMEM_SPEC, PaperStudySpec)
    assert isinstance(MOTUS_SPEC, PaperStudySpec)
    assert len(VILOMEM_SPEC.spec_digest) == 64
    assert len(MOTUS_SPEC.spec_digest) == 64


def test_vilomem_binds_six_final_paper_benchmarks() -> None:
    assert set(VILOMEM_SPEC.benchmark_ids) == {
        "mmmu",
        "mathvista",
        "mathvision",
        "hallusionbench",
        "mmstar",
        "realworldqa",
    }


def test_motus_binds_simulation_and_real_world_protocols() -> None:
    assert set(MOTUS_SPEC.benchmark_ids) == {"robotwin2", "motus-realworld"}
