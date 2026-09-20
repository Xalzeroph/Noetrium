from __future__ import annotations
from noetrium_platform.research.reproduction import ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef, ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle
REPRODUCTION=ReproductionDefinition(
    package="ces_gui_cvpr2026",lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="ces_gui_cvpr2026",title="Training High-Level Schedulers with Execution-Feedback Reinforcement Learning for Long-Horizon GUI Automation",paper_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Deng_Training_High-Level_Schedulers_with_Execution-Feedback_Reinforcement_Learning_for_Long-Horizon_GUI_CVPR_2026_paper.html",year=2026,paper_revision="CVPR 2026 final proceedings"),
    catalog=ReproductionCatalog(domains=("agent","frontier-2026","gui-agent"),families=("gui-agent", "multi-agent", "scheduler", "state-tracking", "reinforcement-learning"),priority=1,benchmark_ids=("aitz", "amex", "gui-odyssey"),platform_pressure=("benchmark","evidence","execution/workflow","experimentation/study","memory","model/request","participant"),method_owned=("Read the user goal, current screen and compressed task state; emit one atomic sub-instruction.", "Use the frozen low-level GUI executor to reason over the sub-instruction and emit the concrete GUI action.", "Capture execution outcome and environment feedback after the GUI action.", "Compress previous state and execution feedback into an updated progress summary.", "Use the new state summary to continue, revise, or terminate the high-level plan."),platform_owned=("MethodProgram execution and Machine Journal truth","provider-independent model/tool dispatch and receipts","content-addressed benchmark task identity","Study/Experiment orchestration and measurement artifacts","run/evidence provenance and replay")),
    assets=(ReproductionAssetRef(ReproductionAssetKind.BENCHMARK,"research/reproductions/ces_gui_cvpr2026/benchmark.py"),ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM,"research/reproductions/ces_gui_cvpr2026/program.py"),ReproductionAssetRef(ReproductionAssetKind.STUDY,"research/reproductions/ces_gui_cvpr2026/study.py")),
    primary_executable="research/reproductions/ces_gui_cvpr2026/program.py",
    reported_results=(

    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="baseline_01",description="GUI-R1 executor alone"),
        ReferenceBaseline(baseline_id="baseline_02",description="GUI-Owl executor alone"),
        ReferenceBaseline(baseline_id="baseline_03",description="zero-shot Qwen2.5-VL"),
        ReferenceBaseline(baseline_id="baseline_04",description="SFT-only scheduler"),
    ),
    blockers=("Matched reproduction requires the pinned CES model/data revisions, exact AITZ/AMEX/GUI-Odyssey cuts and frozen Executor identity.", "Staged-RL claims require Coordinator and State-Tracker optimization receipts plus execution-feedback trajectories."),evidence_refs=(),scientific_tests=("tests/test_scientific_frontier_2026_wave_02.py",),
)
__all__=["REPRODUCTION"]
