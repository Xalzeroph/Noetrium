from __future__ import annotations

from research.reproductions.frontier_2026 import (
    PROGRAM_BY_ID,
    REPRODUCTIONS,
    REPRODUCTION_BY_ID,
)


EXPECTED = {
    "agemem_acl2026",
    "mm_mem_acl2026",
    "mem_gallery_acl2026",
    "os_symphony_acl2026",
    "implement_acl2026",
    "orbit_acl2026",
    "eaglet_acl2026",
    "refact_cvpr2026",
    "ego2web_cvpr2026",
    "mmbench_gui_cvpr2026",
    "echotrail_gui_cvprf2026",
    "star_toggle_cvpr2026",
}


def test_frontier_2026_wave_has_twelve_compiled_reproductions() -> None:
    assert set(REPRODUCTION_BY_ID) == EXPECTED
    assert set(PROGRAM_BY_ID) == EXPECTED
    assert len(REPRODUCTIONS) == 12


def test_frontier_2026_reproductions_are_executable_scientific_specs() -> None:
    for row in REPRODUCTIONS:
        assert row.phases
        assert row.benchmarks
        assert row.protocol
        assert row.metrics
        assert row.baselines
        assert row.ablations
        assert row.reported_claims
        assert row.platform_host
        assert row.execution_blockers
        assert len(row.reproduction_digest) == 64
        assert PROGRAM_BY_ID[row.method_id] is not None
