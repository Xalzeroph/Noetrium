from research.authoring.frontier_2026.wave05 import PAPERS


def test_wave05_contains_ten_distinct_published_reproductions():
    assert len(PAPERS) == 10
    assert len({program.method_id for program, _ in PAPERS.values()}) == 10
    assert len({spec.paper_uri for _, spec in PAPERS.values()}) == 10
    assert all(spec.venue.endswith("2026") for _, spec in PAPERS.values())


def test_wave05_program_and_protocol_are_paper_bound():
    for method_id, (program, spec) in PAPERS.items():
        assert program.method_id == method_id
        assert spec.method_id == method_id
        assert spec.paper_uri.startswith("https://")
        assert spec.benchmark_ids
        assert len(spec.protocol) >= 3
        assert len(spec.metrics) >= 4
        assert len(spec.ablations) >= 3
        assert program.metric_names == spec.metrics
        assert f"{method_id}.phase-transcript" in program.evidence_obligations
        assert f"{method_id}_experiment_manifest" in program.artifact_kinds


def test_wave05_expands_priority_lineages():
    assert {"worldmm_cvpr2026", "octmem_agent_cvpr2026", "glmap_cvpr2026", "evonav_cvpr2026"} <= PAPERS.keys()
    assert {"socialnav_cvpr2026", "navgrpo_cvprf2026", "longvideo_r1_cvpr2026"} <= PAPERS.keys()
    assert {"magma_acl2026", "ama_acl2026", "apex_mem_acl2026"} <= PAPERS.keys()
