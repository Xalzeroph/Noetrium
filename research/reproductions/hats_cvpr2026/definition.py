from __future__ import annotations
from research.reproductions.contracts import ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef, ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle
REPRODUCTION=ReproductionDefinition(
    package="hats_cvpr2026",lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="hats_cvpr2026",title="HATS: Hardness-Aware Trajectory Synthesis for GUI Agents",paper_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Shao_HATS_Hardness-Aware_Trajectory_Synthesis_for_GUI_Agents_CVPR_2026_paper.html",year=2026,paper_revision="CVPR 2026 final proceedings"),
    catalog=ReproductionCatalog(domains=("agent","frontier-2026","gui-agent"),families=("gui-agent", "trajectory-synthesis", "mcts", "data-generation", "hardness-aware-exploration"),priority=1,benchmark_ids=("androidworld", "webarena"),platform_pressure=("benchmark","evidence","execution/workflow","experimentation/study","model/request","perception"),method_owned=("Estimate semantic ambiguity and under-representation of candidate GUI actions.", "Select and expand GUI states with hardness-driven UCB Monte Carlo Tree Search.", "Generate an instruction from the explored action trajectory.", "Replay the synthesized instruction in the environment to reconstruct the trajectory.", "Measure action-level reconstruction recall between instruction replay and source trajectory.", "Inject missing contextual cues until alignment reaches the paper threshold, then admit the trajectory."),platform_owned=("MethodProgram execution and Machine Journal truth","provider-independent model/tool dispatch and receipts","content-addressed benchmark task identity","Study/Experiment orchestration and measurement artifacts","run/evidence provenance and replay")),
    assets=(ReproductionAssetRef(ReproductionAssetKind.BENCHMARK,"research/reproductions/hats_cvpr2026/benchmark.py"),ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM,"research/reproductions/hats_cvpr2026/program.py"),ReproductionAssetRef(ReproductionAssetKind.STUDY,"research/reproductions/hats_cvpr2026/study.py")),
    primary_executable="research/reproductions/hats_cvpr2026/program.py",
    reported_results=(
        ReportedResult(claim_id="hats_androidworld",metric_id="androidworld_score",value=22.6,qualifiers={"benchmark": "AndroidWorld", "unit": "score"}),
        ReportedResult(claim_id="hats_webarena",metric_id="webarena_score",value=20.6,qualifiers={"benchmark": "WebArena", "unit": "score"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="baseline_01",description="OS-Genesis"),
        ReferenceBaseline(baseline_id="baseline_02",description="uniform trajectory synthesis"),
        ReferenceBaseline(baseline_id="baseline_03",description="paper GUI data-generation baselines"),
    ),
    blockers=("Matched reproduction requires the pinned HATS repository, AndroidWorld/WebArena cuts and synthesis-model identities.", "Training-set downstream gains require regenerated accepted trajectories plus downstream agent-training receipts."),evidence_refs=(),scientific_tests=("tests/test_scientific_frontier_2026_wave_02.py",),
)
__all__=["REPRODUCTION"]
