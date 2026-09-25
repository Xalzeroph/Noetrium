from research.authoring.frontier_2026.wave_07_acl2026 import PROGRAMS, REPRODUCTIONS

EXPECTED={"compass_acl2026","octotools_acl2026","bmam_acl2026","clag_acl2026","dcm_agent_acl2026","branch_browse_acl2026","webclipper_acl2026","agentask_acl2026","eti_acl2026","extagents_acl2026"}

def test_wave_has_ten_distinct_formal_reproductions():
    assert {r.method_id for r in REPRODUCTIONS} == EXPECTED
    assert set(PROGRAMS) == EXPECTED
    assert len({r.paper_uri for r in REPRODUCTIONS}) == 10
    assert all("aclanthology.org/2026" in r.paper_uri for r in REPRODUCTIONS)

def test_each_reproduction_has_method_benchmark_protocol_baseline_metrics_and_ablations():
    for r in REPRODUCTIONS:
        assert len(r.phases) >= 6
        assert r.benchmark_ids
        assert len(r.protocol) >= 4
        assert len(r.baselines) >= 3
        assert len(r.metrics) >= 5
        assert len(r.ablations) >= 3
        p=PROGRAMS[r.method_id]
        assert p.program_identity.implementation.method_id == r.method_id

def test_programs_require_replayable_scientific_artifacts():
    for r in REPRODUCTIONS:
        p=PROGRAMS[r.method_id]
        text=repr(p)
        assert "experiment_manifest" in text
        assert "result_table" in text
        assert "metric-artifacts" in text
        assert "model-tool-receipts" in text

def test_wave_spans_memory_web_planning_and_multiagent_lineages():
    ids=EXPECTED
    assert {"bmam_acl2026","clag_acl2026","dcm_agent_acl2026"} <= ids
    assert {"branch_browse_acl2026","webclipper_acl2026"} <= ids
    assert {"agentask_acl2026","eti_acl2026","extagents_acl2026"} <= ids
    assert {"compass_acl2026","octotools_acl2026"} <= ids
