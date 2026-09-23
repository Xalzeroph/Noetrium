from __future__ import annotations
from research.reproductions.contracts import ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef, ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle
REPRODUCTION=ReproductionDefinition(
    package="dejavu_cvpr2026",lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="dejavu_cvpr2026",title="Dejavu: Towards Experience Feedback Learning for Embodied Intelligence",paper_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Wu_Dejavu_Towards_Experience_Feedback_Learning_for_Embodied_Intelligence_CVPR_2026_paper.html",year=2026,paper_revision="CVPR 2026 final proceedings"),
    catalog=ReproductionCatalog(domains=("agent","frontier-2026","vision-language-action"),families=("vision-language-action", "experience-memory", "post-deployment-learning", "reinforcement-learning"),priority=1,benchmark_ids=("libero",),platform_pressure=("benchmark","evidence","execution/workflow","experimentation/study","memory","model/request"),method_owned=("Encode current visual-language state while keeping the base VLA frozen.", "Retrieve a contextually successful prior transition from the live experience bank.", "Predict a retrieval-conditioned residual correction to the frozen VLA action.", "Execute the corrected action under the current rollout horizon.", "Train the residual controller with task return plus semantic-similarity shaping.", "Append successful trajectories and prioritize shorter successful experiences."),platform_owned=("MethodProgram execution and Machine Journal truth","provider-independent model/tool dispatch and receipts","content-addressed benchmark task identity","Study/Experiment orchestration and measurement artifacts","run/evidence provenance and replay")),
    assets=(ReproductionAssetRef(ReproductionAssetKind.BENCHMARK,"research/reproductions/dejavu_cvpr2026/benchmark.py"),ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM,"research/reproductions/dejavu_cvpr2026/program.py"),ReproductionAssetRef(ReproductionAssetKind.STUDY,"research/reproductions/dejavu_cvpr2026/study.py")),
    primary_executable="research/reproductions/dejavu_cvpr2026/program.py",
    reported_results=(
        ReportedResult(claim_id="dejavu_univla_bank1000",metric_id="task_success",value=97.2,qualifiers={"benchmark": "LIBERO", "backbone": "UniVLA", "experience_bank": 1000, "unit": "percent"}),
        ReportedResult(claim_id="dejavu_openvla_bank1000",metric_id="task_success",value=87,qualifiers={"benchmark": "LIBERO", "backbone": "OpenVLA", "experience_bank": 1000, "unit": "percent"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="baseline_01",description="frozen VLA"),
        ReferenceBaseline(baseline_id="baseline_02",description="kNN-RAG"),
        ReferenceBaseline(baseline_id="baseline_03",description="ResAct"),
        ReferenceBaseline(baseline_id="baseline_04",description="R2A"),
        ReferenceBaseline(baseline_id="baseline_05",description="GC-TTT"),
    ),
    blockers=("Matched simulation requires exact LIBERO suite cuts, frozen VLA checkpoints and experience-bank initialization.", "Real-world AgiBot-G1 claims require the physical platform protocol and full rollout evidence."),evidence_refs=(),scientific_tests=("tests/test_scientific_frontier_2026_wave_02.py",),
)
__all__=["REPRODUCTION"]
