from __future__ import annotations
from research.reproductions.contracts import ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef, ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle
REPRODUCTION=ReproductionDefinition(
    package="motus_cvpr2026",lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="motus_cvpr2026",title="Motus: A Unified Latent Action World Model",paper_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Bi_Motus_A_Unified_Latent_Action_World_Model_CVPR_2026_paper.html",year=2026,paper_revision="CVPR 2026 final proceedings"),
    catalog=ReproductionCatalog(domains=("agent","frontier-2026","world-model"),families=("world-model", "vision-language-action", "latent-action", "video-generation", "robotics"),priority=1,benchmark_ids=("robotwin2", "motus-realworld"),platform_pressure=("artifact/lineage","benchmark","evidence","execution/workflow","experimentation/study","memory","model/request","perception"),method_owned=("Encode image/video/language context through the understanding expert.", "Derive optical-flow-based latent delta actions shared across heterogeneous data.", "Select world-model, VLA, inverse-dynamics, video-generation, or video-action joint-prediction mode.", "Route through the Mixture-of-Transformers understanding, action and video-generation experts.", "Apply the UniDiffuser-style scheduler for the selected generation/prediction mode.", "Emit action, future video, inverse action, or joint video-action prediction and preserve the corresponding artifact."),platform_owned=("MethodProgram execution and Machine Journal truth","provider-independent model/tool dispatch and receipts","content-addressed benchmark task identity","Study/Experiment orchestration and measurement artifacts","run/evidence provenance and replay")),
    assets=(ReproductionAssetRef(ReproductionAssetKind.BENCHMARK,"research/reproductions/motus_cvpr2026/benchmark.py"),ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM,"research/reproductions/motus_cvpr2026/program.py"),ReproductionAssetRef(ReproductionAssetKind.STUDY,"research/reproductions/motus_cvpr2026/study.py")),
    primary_executable="research/reproductions/motus_cvpr2026/program.py",
    reported_results=(
        ReportedResult(claim_id="motus_robotwin_avg",metric_id="robotwin_success",value=87.02,qualifiers={"benchmark": "RoboTwin 2.0", "unit": "percent"}),
        ReportedResult(claim_id="motus_vs_xvla_gain",metric_id="robotwin_success_gain",value=15,qualifiers={"reference": "X-VLA", "unit": "percent_relative_or_reported_gain"}),
        ReportedResult(claim_id="motus_vs_pi05_gain",metric_id="robotwin_success_gain",value=45,qualifiers={"reference": "pi_0.5", "unit": "percent_relative_or_reported_gain"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="baseline_01",description="X-VLA"),
        ReferenceBaseline(baseline_id="baseline_02",description="pi_0.5"),
        ReferenceBaseline(baseline_id="baseline_03",description="paper world-model/VLA baselines"),
    ),
    blockers=("Matched reproduction requires the pinned Motus training code/checkpoints, six-layer data pyramid and RoboTwin 2.0 multi-task dataset cut.", "Real-world claims require exact robot hardware/task protocol and synchronized generated-video/action execution evidence."),evidence_refs=(),scientific_tests=('tests/test_scientific_reproduction_current_surface_v1.py',),
)
__all__=["REPRODUCTION"]
