from __future__ import annotations
from research.reproductions.contracts import ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef, ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle
REPRODUCTION=ReproductionDefinition(
    package="echotrail_gui_cvprf2026",lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="echotrail_gui_cvprf2026",title="EchoTrail-GUI: Building Actionable Memory for GUI Agents via Critic-Guided Self-Exploration",paper_uri="https://openaccess.thecvf.com/content/CVPR2026F/html/Li_EchoTrail-GUI_Building_Actionable_Memory_for_GUI_Agents_via_Critic-Guided_Self-Exploration_CVPRF_2026_paper.html",year=2026,paper_revision="CVPR Findings 2026 final proceedings"),
    catalog=ReproductionCatalog(domains=("agent","frontier-2026","gui-agent"),families=("gui-agent", "memory", "self-exploration", "multimodal"),priority=1,benchmark_ids=("androidworld", "androidlab"),platform_pressure=("benchmark","evidence","execution/workflow","experimentation/study","model/request"),method_owned=("Autonomously explore GUI tasks and collect candidate successful trajectories.", "Validate explored trajectories with the reward/critic model.", "Store critic-validated successful trajectories as actionable memories.", "Retrieve relevant prior trajectories for a new GUI task.", "Inject retrieved trajectories as in-context guidance and execute the task."),platform_owned=("MethodProgram execution and Machine Journal truth","provider-independent model/tool dispatch and receipts","content-addressed benchmark task identity","Study/Experiment orchestration and measurement artifacts","run/evidence provenance and replay")),
    assets=(ReproductionAssetRef(ReproductionAssetKind.BENCHMARK,"research/reproductions/echotrail_gui_cvprf2026/benchmark.py"),ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM,"research/reproductions/echotrail_gui_cvprf2026/program.py"),ReproductionAssetRef(ReproductionAssetKind.STUDY,"research/reproductions/echotrail_gui_cvprf2026/study.py")),
    primary_executable="research/reproductions/echotrail_gui_cvprf2026/program.py",
    reported_results=(

    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="baseline_01",description="same GUI agent without memory"),
        ReferenceBaseline(baseline_id="baseline_02",description="final-paper GUI-agent baselines"),
    ),
    blockers=("Matched execution requires the released exploration trajectories/reward model and exact Android benchmark revisions.", "Android environment runs must provide trajectory, critic and final-task evidence receipts."),evidence_refs=(),scientific_tests=('tests/test_scientific_frontier_2026_wave_01.py',),
)
__all__=["REPRODUCTION"]
