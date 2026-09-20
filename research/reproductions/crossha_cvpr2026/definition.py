from __future__ import annotations
from noetrium_platform.research.reproduction import ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef, ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle
REPRODUCTION=ReproductionDefinition(
    package="crossha_cvpr2026",lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="crossha_cvpr2026",title="Training One Model to Master Cross-Level Agentic Actions via Reinforcement Learning",paper_uri="https://openaccess.thecvf.com/content/CVPR2026/html/He_Training_One_Model_to_Master_Cross-Level_Agentic_Actions_via_Reinforcement_CVPR_2026_paper.html",year=2026,paper_revision="CVPR 2026 final proceedings"),
    catalog=ReproductionCatalog(domains=("agent","frontier-2026","minecraft"),families=("minecraft", "open-world-agent", "heterogeneous-actions", "reinforcement-learning", "long-horizon"),priority=1,benchmark_ids=("minecraft-openha",),platform_pressure=("benchmark","evidence","execution/workflow","experimentation/study","memory","model/request","participant"),method_owned=("Observe the Minecraft RGB stream, task instruction and recent trajectory context without privileged state.", "Choose the most suitable action interface and granularity for the current step.", "Generate a motion-, grounding-, or text-level action under the selected interface.", "Execute the human-like mouse/keyboard interaction in Minecraft 1.16.5.", "Collect multi-turn task reward used by Group Relative Policy Optimization.", "Update the unified policy with multi-turn GRPO while preserving heterogeneous action switching."),platform_owned=("MethodProgram execution and Machine Journal truth","provider-independent model/tool dispatch and receipts","content-addressed benchmark task identity","Study/Experiment orchestration and measurement artifacts","run/evidence provenance and replay")),
    assets=(ReproductionAssetRef(ReproductionAssetKind.BENCHMARK,"research/reproductions/crossha_cvpr2026/benchmark.py"),ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM,"research/reproductions/crossha_cvpr2026/program.py"),ReproductionAssetRef(ReproductionAssetKind.STUDY,"research/reproductions/crossha_cvpr2026/study.py")),
    primary_executable="research/reproductions/crossha_cvpr2026/program.py",
    reported_results=(
        ReportedResult(claim_id="crossha_mine_peak",metric_id="mine_success",value=94.7,qualifiers={"benchmark": "Mine Blocks", "metric": "Finished Tasks", "unit": "percent"}),
        ReportedResult(claim_id="crossha_craft_peak",metric_id="craft_success",value=83.3,qualifiers={"benchmark": "Craft Items", "metric": "Finished Tasks", "unit": "percent"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="baseline_01",description="OpenHA"),
        ReferenceBaseline(baseline_id="baseline_02",description="GroundingHA"),
        ReferenceBaseline(baseline_id="baseline_03",description="MotionHA"),
        ReferenceBaseline(baseline_id="baseline_04",description="JARVIS-VLA"),
        ReferenceBaseline(baseline_id="baseline_05",description="Game-TARS"),
    ),
    blockers=("Matched reproduction requires the pinned OpenHA/CrossAgent code, model/data revisions, MineStudio/Minecraft 1.16.5 runtime and exact 800+ task manifest.", "Multi-turn GRPO claims require rollout groups, reward traces, action-space selections and training receipts."),evidence_refs=(),scientific_tests=("tests/test_scientific_frontier_2026_wave_02.py",),
)
__all__=["REPRODUCTION"]
