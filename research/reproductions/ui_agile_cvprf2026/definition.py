from __future__ import annotations
from noetrium_platform.research.reproduction import ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef, ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle
REPRODUCTION=ReproductionDefinition(
    package="ui_agile_cvprf2026",lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="ui_agile_cvprf2026",title="UI-AGILE: Advancing GUI Agents with Effective Reinforcement Learning and Precise Inference-Time Grounding",paper_uri="https://openaccess.thecvf.com/content/CVPR2026F/html/Lian_UI-AGILE_Advancing_GUI_Agents_with_Effective_Reinforcement_Learning_and_Precise_CVPRF_2026_paper.html",year=2026,paper_revision="CVPR Findings 2026 final proceedings"),
    catalog=ReproductionCatalog(domains=("agent","frontier-2026","gui-agent"),families=("gui-agent", "reinforcement-learning", "visual-grounding", "inference-time-selection"),priority=1,benchmark_ids=("screenspot-pro", "screenspot-v2", "androidcontrol"),platform_pressure=("benchmark","evidence","execution/workflow","experimentation/study","model/request","perception"),method_owned=("Use concise task reasoning that balances planning depth with grounding latency.", "Score grounding predictions with a continuous precision-sensitive reward.", "Resample difficult examples through crop-based visual refinement to reduce sparse rewards.", "Decompose high-resolution screens into candidate regions for precise grounding.", "Select the final candidate grounding with the VLM before emitting the GUI action."),platform_owned=("MethodProgram execution and Machine Journal truth","provider-independent model/tool dispatch and receipts","content-addressed benchmark task identity","Study/Experiment orchestration and measurement artifacts","run/evidence provenance and replay")),
    assets=(ReproductionAssetRef(ReproductionAssetKind.BENCHMARK,"research/reproductions/ui_agile_cvprf2026/benchmark.py"),ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM,"research/reproductions/ui_agile_cvprf2026/program.py"),ReproductionAssetRef(ReproductionAssetKind.STUDY,"research/reproductions/ui_agile_cvprf2026/study.py")),
    primary_executable="research/reproductions/ui_agile_cvprf2026/program.py",
    reported_results=(
        ReportedResult(claim_id="ui_agile_screenspot_pro",metric_id="grounding_accuracy",value=48.7,qualifiers={"benchmark": "ScreenSpot-Pro", "model": "UI-AGILE-7B", "setting": "decomposed grounding plus selection", "unit": "percent"}),
        ReportedResult(claim_id="ui_agile_screenspot_v2",metric_id="grounding_accuracy",value=92.1,qualifiers={"benchmark": "ScreenSpot-v2", "model": "UI-AGILE-7B", "unit": "percent"}),
        ReportedResult(claim_id="ui_agile_android_low",metric_id="androidcontrol_low_success",value=77.6,qualifiers={"benchmark": "AndroidControl-Low", "model": "UI-AGILE-7B", "unit": "percent"}),
        ReportedResult(claim_id="ui_agile_android_high",metric_id="androidcontrol_high_success",value=60.6,qualifiers={"benchmark": "AndroidControl-High", "model": "UI-AGILE-7B", "unit": "percent"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="baseline_01",description="JEDI-7B"),
        ReferenceBaseline(baseline_id="baseline_02",description="UI-TARS"),
        ReferenceBaseline(baseline_id="baseline_03",description="GUI-R1"),
        ReferenceBaseline(baseline_id="baseline_04",description="UI-R1-E"),
        ReferenceBaseline(baseline_id="baseline_05",description="Qwen2.5-VL"),
    ),
    blockers=("Matched reproduction requires the pinned UI-AGILE training code/checkpoints, benchmark cuts and image preprocessing.", "Inference-time grounding claims require full candidate-generation/selection traces and timing receipts."),evidence_refs=(),scientific_tests=("tests/test_scientific_frontier_2026_wave_02.py",),
)
__all__=["REPRODUCTION"]
