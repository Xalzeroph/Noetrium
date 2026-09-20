from __future__ import annotations
from noetrium_platform.research.reproduction import ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef, ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle
REPRODUCTION=ReproductionDefinition(
    package="roboagent_cvpr2026",lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="roboagent_cvpr2026",title="RoboAgent: Chaining Basic Capabilities for Embodied Task Planning",paper_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Xu_RoboAgent_Chaining_Basic_Capabilities_for_Embodied_Task_Planning_CVPR_2026_paper.html",year=2026,paper_revision="CVPR 2026 final proceedings"),
    catalog=ReproductionCatalog(domains=("agent","frontier-2026","embodied"),families=("embodied", "capability-routing", "planning", "dagger", "reinforcement-learning"),priority=1,benchmark_ids=("alfworld", "embodiedbench"),platform_pressure=("benchmark","evidence","execution/workflow","experimentation/study","memory","model/request","perception"),method_owned=("Decompose the current embodied task and route the next query to a basic capability.", "Load the selected capability's private context rather than a monolithic global history.", "Solve the routed vision-language subproblem with the shared VLM.", "Execute an atomic embodied action when the selected capability requires environment interaction.", "Return the capability result to the scheduler and update the high-level plan."),platform_owned=("MethodProgram execution and Machine Journal truth","provider-independent model/tool dispatch and receipts","content-addressed benchmark task identity","Study/Experiment orchestration and measurement artifacts","run/evidence provenance and replay")),
    assets=(ReproductionAssetRef(ReproductionAssetKind.BENCHMARK,"research/reproductions/roboagent_cvpr2026/benchmark.py"),ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM,"research/reproductions/roboagent_cvpr2026/program.py"),ReproductionAssetRef(ReproductionAssetKind.STUDY,"research/reproductions/roboagent_cvpr2026/study.py")),
    primary_executable="research/reproductions/roboagent_cvpr2026/program.py",
    reported_results=(

    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="baseline_01",description="single-VLM embodied planner"),
        ReferenceBaseline(baseline_id="baseline_02",description="behavior-cloning only"),
        ReferenceBaseline(baseline_id="baseline_03",description="paper embodied planning baselines"),
    ),
    blockers=("Matched reproduction requires the pinned RoboAgent checkpoint/code, exact ALFWorld and EmbodiedBench-ALFRED cuts, and simulator supervision pipeline.", "BC/DAgger/RL stage claims require complete training-data and optimization receipts."),evidence_refs=(),scientific_tests=("tests/test_scientific_frontier_2026_wave_02.py",),
)
__all__=["REPRODUCTION"]
