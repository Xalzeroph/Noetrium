from __future__ import annotations

from research.reproductions.astranav_memory_cvpr2026.program import METHOD_PROGRAM as ASTRANAV
from research.reproductions.astranav_memory_cvpr2026.study import SPEC as ASTRANAV_SPEC
from research.reproductions.ces_gui_cvpr2026.program import METHOD_PROGRAM as CES
from research.reproductions.ces_gui_cvpr2026.study import SPEC as CES_SPEC
from research.reproductions.crossha_cvpr2026.program import METHOD_PROGRAM as CROSSHA
from research.reproductions.crossha_cvpr2026.study import SPEC as CROSSHA_SPEC
from research.reproductions.d3d_vlp_cvpr2026.program import METHOD_PROGRAM as D3D_VLP
from research.reproductions.d3d_vlp_cvpr2026.study import SPEC as D3D_VLP_SPEC
from research.reproductions.dejavu_cvpr2026.program import METHOD_PROGRAM as DEJAVU
from research.reproductions.dejavu_cvpr2026.study import SPEC as DEJAVU_SPEC
from research.reproductions.foreact_cvpr2026.program import METHOD_PROGRAM as FOREACT
from research.reproductions.foreact_cvpr2026.study import SPEC as FOREACT_SPEC
from research.reproductions.hats_cvpr2026.program import METHOD_PROGRAM as HATS
from research.reproductions.hats_cvpr2026.study import SPEC as HATS_SPEC
from research.reproductions.ishift_cvpr2026.program import METHOD_PROGRAM as ISHIFT
from research.reproductions.ishift_cvpr2026.study import SPEC as ISHIFT_SPEC
from research.reproductions.lmee_cvpr2026.program import METHOD_PROGRAM as LMEE
from research.reproductions.lmee_cvpr2026.study import SPEC as LMEE_SPEC
from research.reproductions.optimusvla_cvpr2026.program import METHOD_PROGRAM as OPTIMUSVLA
from research.reproductions.optimusvla_cvpr2026.study import SPEC as OPTIMUSVLA_SPEC
from research.reproductions.roboagent_cvpr2026.program import METHOD_PROGRAM as ROBOAGENT
from research.reproductions.roboagent_cvpr2026.study import SPEC as ROBOAGENT_SPEC
from research.reproductions.ui_agile_cvprf2026.program import METHOD_PROGRAM as UI_AGILE
from research.reproductions.ui_agile_cvprf2026.study import SPEC as UI_AGILE_SPEC
from research.authoring.frontier_2026.study import PaperStudySpec


PROGRAMS = (
    LMEE,
    OPTIMUSVLA,
    DEJAVU,
    UI_AGILE,
    HATS,
    ISHIFT,
    ROBOAGENT,
    D3D_VLP,
    ASTRANAV,
    CES,
    FOREACT,
    CROSSHA,
)
SPECS = (
    LMEE_SPEC,
    OPTIMUSVLA_SPEC,
    DEJAVU_SPEC,
    UI_AGILE_SPEC,
    HATS_SPEC,
    ISHIFT_SPEC,
    ROBOAGENT_SPEC,
    D3D_VLP_SPEC,
    ASTRANAV_SPEC,
    CES_SPEC,
    FOREACT_SPEC,
    CROSSHA_SPEC,
)


def test_wave_02_has_twelve_registry_independent_programs() -> None:
    assert len(PROGRAMS) == 12
    assert len(SPECS) == 12
    assert len({spec.method_id for spec in SPECS}) == 12
    assert all(program is not None for program in PROGRAMS)


def test_wave_02_specs_bind_real_protocols() -> None:
    for spec in SPECS:
        assert isinstance(spec, PaperStudySpec)
        assert spec.benchmark_ids
        assert spec.protocol
        assert spec.metrics
        assert spec.ablations
        assert len(spec.spec_digest) == 64


def test_wave_02_minecraft_and_memory_pressure_are_present() -> None:
    by_id = {spec.method_id: spec for spec in SPECS}
    assert by_id["crossha_cvpr2026"].benchmark_ids == ("minecraft-openha",)
    assert "goat-bench" in by_id["astranav_memory_cvpr2026"].benchmark_ids
    assert "lmee-bench" in by_id["lmee_cvpr2026"].benchmark_ids
    assert "libero" in by_id["dejavu_cvpr2026"].benchmark_ids
