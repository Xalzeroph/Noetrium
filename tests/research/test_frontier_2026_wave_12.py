from research.authoring.frontier_2026.wave_12 import PROGRAMS, REPRODUCTIONS, STUDY_SPECS


def test_wave12_has_ten_distinct_peer_reviewed_reproductions():
    assert len(REPRODUCTIONS) == 10
    assert len({r.method_id for r in REPRODUCTIONS}) == 10
    assert len({r.paper_uri for r in REPRODUCTIONS}) == 10
    assert all(r.venue in {"ICLR 2025", "CVPR 2025", "CVPR 2026", "ICML 2025", "ACL 2025"} for r in REPRODUCTIONS)


def test_wave12_is_protocol_complete_not_title_scaffold():
    for r in REPRODUCTIONS:
        assert r.method_id in PROGRAMS and r.method_id in STUDY_SPECS
        assert len(r.phases) >= 6
        assert len(r.benchmarks) >= 1
        assert len(r.protocol) >= 5
        assert len(r.metrics) >= 5
        assert len(r.baselines) >= 3
        assert len(r.ablations) >= 3
        assert r.paper_uri.startswith("https://")


def test_wave12_expands_distinct_agent_lineages():
    ids = set(PROGRAMS)
    assert {"adam_iclr2025", "nitrogen_cvpr2026"} <= ids       # Minecraft/open-world + generalist gaming
    assert {"wormi_icml2025", "larm_icml2025", "tango_cvpr2025"} <= ids  # embodied/world-model
    assert "adaptagent_acl2025" in ids                          # multimodal web agent
    assert {"reflectool_acl2025", "kg_agent_acl2025", "toolmaker_acl2025"} <= ids  # tool/software agents
    assert "maporl_acl2025" in ids                              # multi-agent RL


def test_wave12_requires_machine_journal_scientific_receipts():
    for method_id, program in PROGRAMS.items():
        text = repr(program)
        assert "phase-transcript" in text
        assert "model-tool-receipts" in text
        assert "metric-artifacts" in text
        assert "result-table" in text
        assert "experiment_manifest" in text
        assert method_id in text
