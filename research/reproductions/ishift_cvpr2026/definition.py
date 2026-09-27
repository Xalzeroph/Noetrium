from __future__ import annotations
from research.reproductions.contracts import ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef, ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle
REPRODUCTION=ReproductionDefinition(
    package="ishift_cvpr2026",lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="ishift_cvpr2026",title="iSHIFT: Lightweight Slow-Fast GUI Agent with Adaptive Perception",paper_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Mehrotra_iSHIFT_Lightweight_Slow-Fast_GUI_Agent_with_Adaptive_Perception_CVPR_2026_paper.html",year=2026,paper_revision="CVPR 2026 final proceedings"),
    catalog=ReproductionCatalog(domains=("agent","frontier-2026","gui-agent"),families=("gui-agent", "adaptive-perception", "slow-fast-reasoning", "latent-thinking", "efficient-agent"),priority=1,benchmark_ids=("aitw", "androidcontrol", "gui-odyssey", "guiact"),platform_pressure=("benchmark","evidence","execution/workflow","experimentation/study","model/request","perception"),method_owned=("Perform compact implicit deliberation with latent thinking tokens instead of explicit chain-of-thought.", "Decide whether the current action needs fast global perception or slow fine-grained grounding.", "Activate the DINOv2-based Visual Perception Module for object-centered features when the slow path is selected.", "Ground the target element and produce the GUI action.", "Observe the resulting interface state and continue with adaptive reasoning depth."),platform_owned=("MethodProgram execution and Machine Journal truth","provider-independent model/tool dispatch and receipts","content-addressed benchmark task identity","Study/Experiment orchestration and measurement artifacts","run/evidence provenance and replay")),
    assets=(ReproductionAssetRef(ReproductionAssetKind.BENCHMARK,"research/reproductions/ishift_cvpr2026/benchmark.py"),ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM,"research/reproductions/ishift_cvpr2026/program.py"),ReproductionAssetRef(ReproductionAssetKind.STUDY,"research/reproductions/ishift_cvpr2026/study.py")),
    primary_executable="research/reproductions/ishift_cvpr2026/program.py",
    reported_results=(
        ReportedResult(claim_id="ishift_aitw",metric_id="aitw_action_matching",value=76.34,qualifiers={"benchmark": "AITW", "model_size": "2.5B", "unit": "percent"}),
        ReportedResult(claim_id="ishift_gui_odyssey",metric_id="gui_odyssey_success",value=73.97,qualifiers={"benchmark": "GUI Odyssey", "unit": "percent"}),
        ReportedResult(claim_id="ishift_android_low",metric_id="androidcontrol_low_success",value=87.7,qualifiers={"benchmark": "AndroidControl-Low", "unit": "percent"}),
        ReportedResult(claim_id="ishift_android_high",metric_id="androidcontrol_high_success",value=65.6,qualifiers={"benchmark": "AndroidControl-High", "unit": "percent"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="baseline_01",description="Qwen2-VL baseline"),
        ReferenceBaseline(baseline_id="baseline_02",description="ShowUI"),
        ReferenceBaseline(baseline_id="baseline_03",description="TongUI"),
        ReferenceBaseline(baseline_id="baseline_04",description="CogAgent"),
        ReferenceBaseline(baseline_id="baseline_05",description="SeeClick"),
        ReferenceBaseline(baseline_id="baseline_06",description="Aguvis"),
    ),
    blockers=("Matched reproduction requires the pinned iSHIFT code/checkpoint, DINOv2/SAM/base-model revisions and exact benchmark preprocessing.", "Efficiency claims require matched hardware, token accounting and inference traces."),evidence_refs=(),scientific_tests=('tests/test_scientific_reproduction_current_surface_v1.py',),
)
__all__=["REPRODUCTION"]
