from research.authoring.frontier_2026.wave_09 import REPRODUCTIONS, PROGRAMS, STUDY_SPECS


def test_wave09_has_ten_distinct_peer_reviewed_reproductions():
    assert len(REPRODUCTIONS) == 10
    assert len({r.method_id for r in REPRODUCTIONS}) == 10
    assert all("2026" in r.venue for r in REPRODUCTIONS)
    assert all(r.paper_uri.startswith("https://") for r in REPRODUCTIONS)


def test_wave09_is_protocol_complete_not_title_scaffold():
    for r in REPRODUCTIONS:
        assert len(r.phases) >= 5
        assert len(r.protocol) >= 5
        assert len(r.metrics) >= 5
        assert len(r.baselines) >= 3
        assert len(r.ablations) >= 3
        assert r.method_id in PROGRAMS
        assert r.method_id in STUDY_SPECS
        assert len({phase[1] for phase in r.phases}) == len(r.phases)


def test_wave09_covers_memory_embodied_planning_and_multiagent_frontiers():
    ids = set(PROGRAMS)
    assert {"memory_r1_acl2026", "me_agent_findings_acl2026", "conflict_aware_memory_acl2026"} <= ids
    assert {"faer_findings_acl2026", "plan_rewardbench_acl2026"} <= ids
    assert {"amata_acl2026", "agentic_neural_network_findings_acl2026", "sema_rag_findings_acl2026", "mass_rag_findings_acl2026"} <= ids


def test_wave09_programs_preserve_paper_owned_receipt_contracts():
    for r in REPRODUCTIONS:
        compiled = PROGRAMS[r.method_id]
        text = repr(compiled)
        assert r.method_id in text
        assert "result-table" in text
        assert "experiment_manifest" in text
