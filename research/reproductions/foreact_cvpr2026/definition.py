from __future__ import annotations
from research.reproductions.contracts import ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef, ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle
REPRODUCTION=ReproductionDefinition(
    package="foreact_cvpr2026",lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="foreact_cvpr2026",title="ForeAct: Steering Your VLA with Efficient Visual Foresight Planning",paper_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Zhang_ForeAct_Steering_Your_VLA_with_Efficient_Visual_Foresight_Planning_CVPR_2026_paper.html",year=2026,paper_revision="CVPR 2026 final proceedings"),
    catalog=ReproductionCatalog(domains=("agent","frontier-2026","vision-language-action"),families=("vision-language-action", "visual-foresight", "planning", "world-model", "robotic-manipulation"),priority=1,benchmark_ids=("foreact-real11",),platform_pressure=("benchmark","evidence","execution/workflow","experimentation/study","memory","model/request","participant"),method_owned=("Encode current multi-view robot observations and the high-level task instruction.", "Infer the next semantic subtask description.", "Generate the predicted future observation conditioned on current vision and the subtask.", "Attach imagined future observations to the VLA visual context without modifying VLA architecture.", "Produce and execute the next visuo-motor action chunk.", "Use the resulting observation to refresh foresight planning for the next step."),platform_owned=("MethodProgram execution and Machine Journal truth","provider-independent model/tool dispatch and receipts","content-addressed benchmark task identity","Study/Experiment orchestration and measurement artifacts","run/evidence provenance and replay")),
    assets=(ReproductionAssetRef(ReproductionAssetKind.BENCHMARK,"research/reproductions/foreact_cvpr2026/benchmark.py"),ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM,"research/reproductions/foreact_cvpr2026/program.py"),ReproductionAssetRef(ReproductionAssetKind.STUDY,"research/reproductions/foreact_cvpr2026/study.py")),
    primary_executable="research/reproductions/foreact_cvpr2026/program.py",
    reported_results=(
        ReportedResult(claim_id="foreact_real11",metric_id="task_success",value=87.4,qualifiers={"benchmark": "11 real-world multi-step tasks", "unit": "percent"}),
        ReportedResult(claim_id="foreact_pi0_baseline",metric_id="task_success",value=46.5,qualifiers={"benchmark": "11 real-world multi-step tasks", "model": "pi_0", "unit": "percent"}),
        ReportedResult(claim_id="foreact_text_guidance",metric_id="task_success",value=57.1,qualifiers={"benchmark": "11 real-world multi-step tasks", "setting": "textual subtask guidance", "unit": "percent"}),
        ReportedResult(claim_id="foreact_future_latency",metric_id="foresight_latency",value=0.33,qualifiers={"unit": "second", "hardware": "H100", "resolution": "640x480"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="baseline_01",description="pi_0"),
        ReferenceBaseline(baseline_id="baseline_02",description="pi_0 plus text subtask guidance"),
        ReferenceBaseline(baseline_id="baseline_03",description="pi_0.5"),
    ),
    blockers=("Matched reproduction requires the pinned ForeAct generator/checkpoints, exact 11-task real-world protocol and VLA backbone snapshots.", "Physical-robot claims require episode-level execution receipts and synchronized camera/action evidence."),evidence_refs=(),scientific_tests=('tests/test_scientific_reproduction_current_surface_v1.py',),
)
__all__=["REPRODUCTION"]
