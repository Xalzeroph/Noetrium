from __future__ import annotations
from research.reproductions.contracts import ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef, ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle
REPRODUCTION=ReproductionDefinition(
    package="mmbench_gui_cvpr2026",lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="mmbench_gui_cvpr2026",title="MMBench-GUI: A Unified Hierarchical Evaluation Framework for Multi-Platform GUI Agents",paper_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Wang_MMBench-GUI_A_Unified_Hierarchical_Evaluation_Framework_for_Multi-Platform_GUI_Agents_CVPR_2026_paper.html",year=2026,paper_revision="CVPR 2026 final proceedings"),
    catalog=ReproductionCatalog(domains=("agent","frontier-2026","benchmark"),families=("benchmark", "gui-agent", "multiplatform", "evaluation"),priority=1,benchmark_ids=("mmbench-gui",),platform_pressure=("benchmark","evidence","execution/workflow","experimentation/study","model/request"),method_owned=("Evaluate GUI content understanding.", "Evaluate visual element grounding.", "Evaluate end-to-end task automation.", "Evaluate cross-application task collaboration.", "Compute Efficiency-Quality-Aware score from success and action redundancy."),platform_owned=("MethodProgram execution and Machine Journal truth","provider-independent model/tool dispatch and receipts","content-addressed benchmark task identity","Study/Experiment orchestration and measurement artifacts","run/evidence provenance and replay")),
    assets=(ReproductionAssetRef(ReproductionAssetKind.BENCHMARK,"research/reproductions/mmbench_gui_cvpr2026/benchmark.py"),ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM,"research/reproductions/mmbench_gui_cvpr2026/program.py"),ReproductionAssetRef(ReproductionAssetKind.STUDY,"research/reproductions/mmbench_gui_cvpr2026/study.py")),
    primary_executable="research/reproductions/mmbench_gui_cvpr2026/program.py",
    reported_results=(
        ReportedResult(claim_id="mmbench_gui_platform_count",metric_id="platform_count",value=6,qualifiers={"platforms": "Windows/macOS/Linux/iOS/Android/Web", "source": "CVPR 2026 final paper"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="baseline_01",description="GUI agents evaluated in the final CVPR paper"),
    ),
    blockers=("Matched execution requires the released benchmark revision plus six platform images/states and evaluator code.", "Cross-platform GUI results require executable environment receipts rather than static benchmark metadata."),evidence_refs=(),scientific_tests=('tests/test_scientific_frontier_2026_wave_01.py',),
)
__all__=["REPRODUCTION"]
