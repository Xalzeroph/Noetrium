from __future__ import annotations
from research.reproductions.contracts import ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef, ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle
REPRODUCTION=ReproductionDefinition(
    package="optimusvla_cvpr2026",lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="optimusvla_cvpr2026",title="Global Prior Meets Local Consistency: Dual-Memory Augmented Vision-Language-Action Model for Efficient Robotic Manipulation",paper_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Li_Global_Prior_Meets_Local_Consistency_Dual-Memory_Augmented_Vision-Language-Action_Model_for_CVPR_2026_paper.html",year=2026,paper_revision="CVPR 2026 final proceedings"),
    catalog=ReproductionCatalog(domains=("agent","frontier-2026","vision-language-action"),families=("vision-language-action", "dual-memory", "robotic-manipulation", "efficient-inference"),priority=1,benchmark_ids=("libero", "calvin", "robotwin2-hard"),platform_pressure=("benchmark","evidence","execution/workflow","experimentation/study","memory","model/request"),method_owned=("Encode task language and current observations into the VLA multimodal representation.", "Retrieve a task-level prior trajectory from Global Prior Memory.", "Encode executed action history into Local Consistency Memory and infer task progress.", "Generate the next action chunk from prior-initialized flow with adaptive NFE scheduling.", "Apply local temporal-consistency constraints to the generated action chunk.", "Execute the action chunk and update local action-history memory."),platform_owned=("MethodProgram execution and Machine Journal truth","provider-independent model/tool dispatch and receipts","content-addressed benchmark task identity","Study/Experiment orchestration and measurement artifacts","run/evidence provenance and replay")),
    assets=(ReproductionAssetRef(ReproductionAssetKind.BENCHMARK,"research/reproductions/optimusvla_cvpr2026/benchmark.py"),ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM,"research/reproductions/optimusvla_cvpr2026/program.py"),ReproductionAssetRef(ReproductionAssetKind.STUDY,"research/reproductions/optimusvla_cvpr2026/study.py")),
    primary_executable="research/reproductions/optimusvla_cvpr2026/program.py",
    reported_results=(
        ReportedResult(claim_id="optimus_libero_avg",metric_id="task_success",value=98.6,qualifiers={"benchmark": "LIBERO", "unit": "percent"}),
        ReportedResult(claim_id="optimus_calvin_gain",metric_id="calvin_gain",value=13.5,qualifiers={"benchmark": "CALVIN", "unit": "percent", "reference": "pi_0"}),
        ReportedResult(claim_id="optimus_robotwin_hard",metric_id="task_success",value=38,qualifiers={"benchmark": "RoboTwin 2.0 Hard", "unit": "percent"}),
        ReportedResult(claim_id="optimus_speedup",metric_id="inference_speedup",value=2.9,qualifiers={"unit": "x"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="baseline_01",description="pi_0"),
        ReferenceBaseline(baseline_id="baseline_02",description="paper VLA baselines"),
        ReferenceBaseline(baseline_id="baseline_03",description="single-memory ablations"),
    ),
    blockers=("Matched reproduction requires the pinned OptimusVLA code/checkpoints plus exact LIBERO, CALVIN and RoboTwin 2.0 cuts.", "Real-world long-horizon claims require the GALAXEA robot protocol and physical execution receipts."),evidence_refs=(),scientific_tests=('tests/test_scientific_reproduction_current_surface_v1.py',),
)
__all__=["REPRODUCTION"]
