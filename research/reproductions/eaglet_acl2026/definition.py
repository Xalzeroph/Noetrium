from __future__ import annotations
from research.reproductions.contracts import ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef, ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle
REPRODUCTION=ReproductionDefinition(
    package="eaglet_acl2026",
    lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="eaglet_acl2026",title="A Goal Without a Plan Is Just a Wish: Efficient and Effective Global Planner Training for Long-Horizon Agent Tasks",paper_uri="https://aclanthology.org/2026.acl-long.597/",year=2026,paper_revision="ACL 2026 final proceedings"),
    catalog=ReproductionCatalog(
        domains=("agent","frontier-2026","planning"),
        families=("planning", "long-horizon", "reinforcement-learning", "agent-training"),
        priority=1,
        benchmark_ids=("scienceworld", "alfworld", "webshop"),
        platform_pressure=("benchmark","evidence","execution/workflow","experimentation/study","model/request"),
        method_owned=("Synthesize candidate global plans with the teacher LLM.", "Apply homologous consensus filtering to retain high-quality plans.", "Fine-tune the planner on filtered plans for cold start.", "Optimize with executor capability-gain reward without a learned reward model.", "Generate a global plan and execute it with the downstream executor agent."),
        platform_owned=("MethodProgram execution and Machine Journal truth","provider-independent model/tool dispatch and receipts","content-addressed benchmark task identity","Study/Experiment orchestration and measurement artifacts","run/evidence provenance and replay"),
    ),
    assets=(
        ReproductionAssetRef(ReproductionAssetKind.BENCHMARK,"research/reproductions/eaglet_acl2026/benchmark.py"),
        ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM,"research/reproductions/eaglet_acl2026/program.py"),
        ReproductionAssetRef(ReproductionAssetKind.STUDY,"research/reproductions/eaglet_acl2026/study.py"),
    ),
    primary_executable="research/reproductions/eaglet_acl2026/program.py",
    reported_results=(
        ReportedResult(claim_id="eaglet_scienceworld",metric_id="task_success",value=83.6,qualifiers={"benchmark": "ScienceWorld", "configuration": "EAGLET+GiGPO"}),
        ReportedResult(claim_id="eaglet_alfworld",metric_id="task_success",value=91.8,qualifiers={"benchmark": "ALFWorld", "configuration": "EAGLET+GiGPO"}),
        ReportedResult(claim_id="eaglet_webshop",metric_id="task_success",value=86.2,qualifiers={"benchmark": "WebShop", "configuration": "EAGLET+GiGPO"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="baseline_01",description="executor without planner"),
        ReferenceBaseline(baseline_id="baseline_02",description="SFT-only planner"),
        ReferenceBaseline(baseline_id="baseline_03",description="GiGPO+MPO"),
        ReferenceBaseline(baseline_id="baseline_04",description="KnowAgent"),
        ReferenceBaseline(baseline_id="baseline_05",description="RL planner baselines"),
    ),
    blockers=("Matched execution requires released planner data/configuration, teacher/model revisions and exact benchmark cuts.", "Training-cost claims require complete planner-training compute receipts."),
    evidence_refs=(),
    scientific_tests=("tests/test_scientific_frontier_2026_wave_01.py",),
)
__all__=["REPRODUCTION"]
