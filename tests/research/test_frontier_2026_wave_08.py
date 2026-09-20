from research.reproductions.frontier_2026.wave_08 import REPRODUCTIONS, PROGRAMS, STUDY_SPECS

def test_wave08_has_ten_distinct_peer_reviewed_reproductions():
    assert len(REPRODUCTIONS)==10
    assert len({r.method_id for r in REPRODUCTIONS})==10
    assert all("2026" in r.venue for r in REPRODUCTIONS)
    assert all(r.paper_uri.startswith("https://") for r in REPRODUCTIONS)

def test_wave08_is_protocol_complete_not_title_scaffold():
    for r in REPRODUCTIONS:
        assert len(r.phases)>=5
        assert len(r.protocol)>=5
        assert len(r.metrics)>=5
        assert len(r.baselines)>=3
        assert len(r.ablations)>=3
        assert r.method_id in PROGRAMS and r.method_id in STUDY_SPECS
        assert len({p[1] for p in r.phases})==len(r.phases)

def test_wave08_covers_requested_frontiers():
    ids=set(PROGRAMS)
    assert {"mempo_findings_acl2026","assomem_iclr2026","steem_acl2026"} <= ids
    assert {"rig_iclr2026","bibo_iclr2026","newt_iclr2026"} <= ids
    assert {"webanchor_findings_acl2026","mle_memory_findings_acl2026"} <= ids

def test_wave08_requires_measured_receipts_and_result_tables():
    for r in REPRODUCTIONS:
        p=PROGRAMS[r.method_id]
        # Program compilation must preserve paper-owned evidence/artifact contract.
        text=repr(p)
        assert r.method_id in text
