from research.authoring.frontier_2026.wave_11 import PROGRAMS, REPRODUCTIONS, STUDY_SPECS


def test_wave11_has_ten_distinct_peer_reviewed_reproductions():
    assert len(REPRODUCTIONS) == 10
    assert len({r.method_id for r in REPRODUCTIONS}) == 10
    assert len({r.paper_uri for r in REPRODUCTIONS}) == 10
    assert all(r.venue in {"ICLR 2026", "CVPR 2026", "ICML 2026"} for r in REPRODUCTIONS)


def test_wave11_is_protocol_complete_not_title_scaffold():
    for r in REPRODUCTIONS:
        assert r.method_id in PROGRAMS and r.method_id in STUDY_SPECS
        assert len(r.phases) >= 6
        assert len(r.benchmarks) >= 1
        assert len(r.protocol) >= 5
        assert len(r.metrics) >= 5
        assert len(r.baselines) >= 3
        assert len(r.ablations) >= 3
        assert r.paper_uri.startswith("https://")


def test_wave11_covers_requested_lineages():
    ids = set(PROGRAMS)
    assert "xenon_iclr2026" in ids                 # Minecraft
    assert {"fast_thinkact_cvpr2026", "xl_vla_cvpr2026", "lac_wm_icml2026"} <= ids  # VLA/world model
    assert "agent_jit_icml2026" in ids             # web planning/scheduling
    assert {"evomas_icml2026", "lmac_icml2026", "evocf_icml2026"} <= ids            # multi-agent
    assert "hiper_icml2026" in ids                 # hierarchical agent RL


def test_wave11_requires_scientific_receipts_and_results():
    for method_id, program in PROGRAMS.items():
        text = repr(program)
        assert "phase-transcript" in text
        assert "model-tool-receipts" in text
        assert "metric-artifacts" in text
        assert "result-table" in text
        assert "experiment_manifest" in text
        assert method_id in text
