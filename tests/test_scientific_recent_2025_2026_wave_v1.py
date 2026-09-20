from __future__ import annotations
import importlib
from noetrium_platform.research.reproduction import ReproductionAssetKind

WAVE = (
    ("videoarm_cvpr2026", 2026, 2, 5, true),
    ("watch_learn_cvpr2026", 2026, 2, 5, true),
    ("lvagent_iccv2025", 2025, 3, 5, true),
    ("embodied_videoagent_iccv2025", 2025, 3, 5, false),
    ("openwebvoyager_acl2025", 2025, 2, 5, true),
    ("adaptagent_acl2025", 2025, 3, 5, true),
    ("r2d2_acl2025", 2025, 2, 5, true),
    ("cer_acl2025", 2025, 3, 5, true),
    ("dars_acl2025", 2025, 2, 5, true),
    ("webagent_r1_emnlp2025", 2025, 2, 5, true),
)

def test_recent_2025_2026_peer_reviewed_wave_is_real_protocol_work() -> None:
    assert len(WAVE) == 10
    assert all(year >= 2025 for _, year, _, _, _ in WAVE)
    for package, year, minimum_claims, minimum_phases, _ in WAVE:
        definition = importlib.import_module(f"research.reproductions.{package}.definition").REPRODUCTION
        program_module = importlib.import_module(f"research.reproductions.{package}.program")
        program = next(value for name, value in vars(program_module).items() if name.endswith("_METHOD_PROGRAM"))
        assert definition.identity.year == year
        assert definition.lifecycle.value == "protocol_bound"
        assert definition.catalog.benchmark_ids
        assert len(definition.reported_results) >= minimum_claims
        assert definition.reference_baselines
        kinds = {asset.kind for asset in definition.assets}
        assert {ReproductionAssetKind.FIDELITY, ReproductionAssetKind.BENCHMARK, ReproductionAssetKind.METHOD_PROGRAM, ReproductionAssetKind.STUDY}.issubset(kinds)
        assert len(program.graph.nodes) >= minimum_phases + 1
        assert definition.evidence_refs == ()
