from research.authoring.frontier_2026.wave06 import PAPERS


def test_wave06_contains_ten_distinct_published_reproductions():
    assert len(PAPERS) == 10
    assert len({program.method_id for program, _ in PAPERS.values()}) == 10
    assert len({spec.paper_uri for _, spec in PAPERS.values()}) == 10
    assert all("2026" in spec.venue for _, spec in PAPERS.values())


def test_wave06_program_protocol_and_evidence_are_paper_bound():
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
        assert f"{method_id}.model-tool-receipts" in program.evidence_obligations
        assert f"{method_id}.metric-artifacts" in program.evidence_obligations
        assert f"{method_id}_trajectory" in program.artifact_kinds
        assert f"{method_id}_experiment_manifest" in program.artifact_kinds
        assert f"{method_id}_result_table" in program.artifact_kinds


def test_wave06_expands_priority_lineages_without_kernel_paper_types():
    assert {"vismem_cvpr2026", "r4_cvpr2026", "refact_cvpr2026", "longvideoagent_acl2026"} <= PAPERS.keys()
    assert {"embodiedsplat_cvpr2026", "implement_acl2026", "embodied_reasoner_acl2026", "evu_acl2026"} <= PAPERS.keys()
    assert {"agentrevive_acl2026", "agentslimming_acl2026"} <= PAPERS.keys()


def test_wave06_programs_have_nontrivial_method_semantics():
    for program, _ in PAPERS.values():
        # A paper reproduction must encode a real multi-stage method rather than a single placeholder node.
        assert len(program.nodes) >= 5
