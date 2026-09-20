from __future__ import annotations
from noetrium_platform.research.reproduction import ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef, ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle
REPRODUCTION=ReproductionDefinition(
    package="star_toggle_cvpr2026",lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="star_toggle_cvpr2026",title="See, Think, Act: Teaching Multimodal Agents to Effectively Interact with GUI by Identifying Toggles",paper_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Wu_See_Think_Act_Teaching_Multimodal_Agents_to_Effectively_Interact_with_CVPR_2026_paper.html",year=2026,paper_revision="CVPR 2026 final proceedings"),
    catalog=ReproductionCatalog(domains=("agent","frontier-2026","gui-agent"),families=("gui-agent", "state-reasoning", "multimodal", "grounding"),priority=1,benchmark_ids=("state-control-benchmark",),platform_pressure=("benchmark","evidence","execution/workflow","experimentation/study","model/request"),method_owned=("Perceive the current binary toggle state from the GUI.", "Infer the desired toggle state from the user instruction.", "Compare current and desired states and decide whether interaction is required.", "Execute the toggle action only when a state transition is required.", "Verify the post-action state and retain evidence."),platform_owned=("MethodProgram execution and Machine Journal truth","provider-independent model/tool dispatch and receipts","content-addressed benchmark task identity","Study/Experiment orchestration and measurement artifacts","run/evidence provenance and replay")),
    assets=(ReproductionAssetRef(ReproductionAssetKind.BENCHMARK,"research/reproductions/star_toggle_cvpr2026/benchmark.py"),ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM,"research/reproductions/star_toggle_cvpr2026/program.py"),ReproductionAssetRef(ReproductionAssetKind.STUDY,"research/reproductions/star_toggle_cvpr2026/study.py")),
    primary_executable="research/reproductions/star_toggle_cvpr2026/program.py",
    reported_results=(
        ReportedResult(claim_id="star_toggle_gain",metric_id="toggle_execution_accuracy_gain",value=30,qualifiers={"unit": "percentage_points_or_more", "source": "CVPR 2026 final paper abstract", "lower_bound": True}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="baseline_01",description="same four multimodal agents without StaR"),
        ReferenceBaseline(baseline_id="baseline_02",description="final-paper GUI-agent baselines"),
    ),
    blockers=("Matched execution requires the released State Control Benchmark plus exact four agent/model revisions.", "Dynamic GUI claims require live environment receipts and post-action state verification."),evidence_refs=(),scientific_tests=("tests/test_scientific_frontier_2026_wave_01.py",),
)
__all__=["REPRODUCTION"]
