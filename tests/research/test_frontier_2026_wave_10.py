from research.authoring.frontier_2026.wave_10 import REPRODUCTIONS, PROGRAMS, STUDY_SPECS


def test_wave10_has_ten_distinct_peer_reviewed_reproductions():
    assert len(REPRODUCTIONS) == 10
    assert len({r.method_id for r in REPRODUCTIONS}) == 10
    assert all("2026" in r.venue for r in REPRODUCTIONS)
    assert all(r.paper_uri.startswith("https://") for r in REPRODUCTIONS)


def test_wave10_is_protocol_complete_not_title_scaffold():
    for r in REPRODUCTIONS:
        assert len(r.phases) >= 6
        assert len(r.protocol) >= 5
        assert len(r.metrics) >= 5
        assert len(r.baselines) >= 3
        assert len(r.ablations) >= 3
        assert r.method_id in PROGRAMS
        assert r.method_id in STUDY_SPECS
        assert len({p[1] for p in r.phases}) == len(r.phases)


def test_wave10_expands_memory_multimodal_and_embodied_lineages():
    ids = set(PROGRAMS)
    assert {"samem_findings_acl2026", "agentocr_acl2026", "lightmem_acl2026", "metacognitive_memory_findings_acl2026", "experience_following_acl2026"} <= ids
    assert {"visual_inception_acl2026", "ovsegdt_cvpr2026", "agentsafe_cvpr2026", "fantasyvln_cvpr2026", "sage_cvpr2026"} <= ids


def test_wave10_preserves_scientific_receipt_contract():
    for r in REPRODUCTIONS:
        text = repr(PROGRAMS[r.method_id])
        assert r.method_id in text
        assert "result-table" in text
        assert "experiment_manifest" in text
        assert "Machine Journal" in " ".join(r.protocol)
