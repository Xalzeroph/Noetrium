from __future__ import annotations
from research.reproductions.contracts import ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef, ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle
REPRODUCTION=ReproductionDefinition(
    package="d3d_vlp_cvpr2026",lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="d3d_vlp_cvpr2026",title="D3D-VLP: Dynamic 3D Vision-Language-Planning Model for Embodied Grounding and Navigation",paper_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Wang_D3D-VLP_Dynamic_3D_Vision-Language-Planning_Model_for_Embodied_Grounding_and_Navigation_CVPR_2026_paper.html",year=2026,paper_revision="CVPR 2026 final proceedings"),
    catalog=ReproductionCatalog(domains=("agent","frontier-2026","embodied"),families=("embodied", "3d-reasoning", "planning", "grounding", "navigation", "dynamic-replanning"),priority=1,benchmark_ids=("r2r-ce", "reverie-ce", "navrag-ce", "hm3d-ovon", "sg3d"),platform_pressure=("benchmark","evidence","execution/workflow","experimentation/study","memory","model/request","perception"),method_owned=("Update multi-level 3D memory with observations, trajectory history, grounded targets and prior plans.", "Generate a dynamic 3D chain-of-thought spanning planning, grounding, navigation and question answering.", "Ground the next target or detect that the current target is missing.", "Generate or revise the plan using current 3D memory and grounding feedback.", "Execute navigation actions toward the grounded target.", "Use blocked-plan or missing-target feedback to trigger another reasoning cycle."),platform_owned=("MethodProgram execution and Machine Journal truth","provider-independent model/tool dispatch and receipts","content-addressed benchmark task identity","Study/Experiment orchestration and measurement artifacts","run/evidence provenance and replay")),
    assets=(ReproductionAssetRef(ReproductionAssetKind.BENCHMARK,"research/reproductions/d3d_vlp_cvpr2026/benchmark.py"),ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM,"research/reproductions/d3d_vlp_cvpr2026/program.py"),ReproductionAssetRef(ReproductionAssetKind.STUDY,"research/reproductions/d3d_vlp_cvpr2026/study.py")),
    primary_executable="research/reproductions/d3d_vlp_cvpr2026/program.py",
    reported_results=(
        ReportedResult(claim_id="d3d_hybrid_samples",metric_id="hybrid_training_sample_count",value=10000000,qualifiers={"unit": "samples"}),
        ReportedResult(claim_id="d3d_real_scans",metric_id="real_scan_count",value=5000,qualifiers={"unit": "scans"}),
        ReportedResult(claim_id="d3d_synthetic_scenes",metric_id="synthetic_scene_count",value=20000,qualifiers={"unit": "scenes"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="baseline_01",description="end-to-end VLA/VLN models"),
        ReferenceBaseline(baseline_id="baseline_02",description="modular planning-grounding-navigation systems"),
        ReferenceBaseline(baseline_id="baseline_03",description="paper benchmark baselines"),
    ),
    blockers=("Matched reproduction requires the pinned D3D-VLP code plus released 10M hybrid training data and exact simulator cuts.", "Real-world mobile-manipulation claims require the physical evaluation protocol and robot execution evidence."),evidence_refs=(),scientific_tests=('tests/test_scientific_reproduction_current_surface_v1.py',),
)
__all__=["REPRODUCTION"]
