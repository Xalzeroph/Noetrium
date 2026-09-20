from __future__ import annotations
from noetrium_platform.research.reproduction import ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef, ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle
REPRODUCTION=ReproductionDefinition(
    package="refact_cvpr2026",lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="refact_cvpr2026",title="ReFAct: Empowering Multimodal Web Agents with Visual and Context Focusing",paper_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Wu_ReFAct_Empowering_Multimodal_Web_Agents_with_Visual_and_Context_Focusing_CVPR_2026_paper.html",year=2026,paper_revision="CVPR 2026 final proceedings"),
    catalog=ReproductionCatalog(domains=("agent","frontier-2026","multimodal-web-agent"),families=("multimodal-web-agent", "active-perception", "memory", "context-management"),priority=1,benchmark_ids=("groundedvqa",),platform_pressure=("benchmark","evidence","execution/workflow","experimentation/study","model/request"),method_owned=("Reason over the current multimodal web-search state.", "Actively ground and filter visual information relevant to the current reasoning step.", "Use external-memory Defocus/Refocus operations to control retained context density.", "Execute the next web-search or navigation action.", "Observe new multimodal evidence and update the working context."),platform_owned=("MethodProgram execution and Machine Journal truth","provider-independent model/tool dispatch and receipts","content-addressed benchmark task identity","Study/Experiment orchestration and measurement artifacts","run/evidence provenance and replay")),
    assets=(ReproductionAssetRef(ReproductionAssetKind.BENCHMARK,"research/reproductions/refact_cvpr2026/benchmark.py"),ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM,"research/reproductions/refact_cvpr2026/program.py"),ReproductionAssetRef(ReproductionAssetKind.STUDY,"research/reproductions/refact_cvpr2026/study.py")),
    primary_executable="research/reproductions/refact_cvpr2026/program.py",
    reported_results=(

    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="baseline_01",description="base multimodal web-search agent"),
        ReferenceBaseline(baseline_id="baseline_02",description="final-paper web-agent baselines"),
    ),
    blockers=("Matched execution requires the released GroundedVQA cut, reproducible web state, prompts/model snapshot and grounding implementation.", "Final quantitative claims require paper-table extraction plus real multimodal web execution receipts."),evidence_refs=(),scientific_tests=("tests/test_scientific_frontier_2026_wave_01.py",),
)
__all__=["REPRODUCTION"]
