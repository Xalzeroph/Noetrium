from research.authoring.frontier_2026.wave04 import PROGRAMS, SPECS


def test_wave04_contains_ten_peer_reviewed_reproductions():
    assert len(PROGRAMS) == 10
    assert set(PROGRAMS) == set(SPECS)
    assert all(spec.venue for spec in SPECS.values())
    assert all(spec.paper_uri.startswith("https://") for spec in SPECS.values())
    assert all(len(spec.benchmark_ids) >= 1 for spec in SPECS.values())
    assert all(len(spec.metrics) >= 4 for spec in SPECS.values())
    assert all(len(spec.ablations) >= 3 for spec in SPECS.values())
    assert all(len(spec.protocol) >= 3 for spec in SPECS.values())


def test_wave04_prioritizes_memory_embodiment_minecraft_and_gui():
    assert "echo_cvpr2026" in PROGRAMS
    assert "pred_eqa_cvpr2026" in PROGRAMS
    assert "m3_agent_iclr2026" in PROGRAMS
    assert "mikasa_iclr2026" in PROGRAMS
    assert "personalalign_acl2026" in PROGRAMS
    assert "learnact_acl2026" in PROGRAMS
    assert "infiguiagent_eacl2026" in PROGRAMS
    assert "agemem_acl2026" in PROGRAMS
    assert "magnet_acl2026" in PROGRAMS
    assert "memoryagentbench_iclr2026" in PROGRAMS
