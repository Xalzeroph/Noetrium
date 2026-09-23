from __future__ import annotations
from research.reproductions.contracts import ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef, ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle
REPRODUCTION=ReproductionDefinition(
    package="implement_acl2026",
    lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="implement_acl2026",title="Model-Based Imaginative Planning for Embodied Agents",paper_uri="https://aclanthology.org/2026.acl-long.827/",year=2026,paper_revision="ACL 2026 final proceedings"),
    catalog=ReproductionCatalog(
        domains=("agent","frontier-2026","embodied"),
        families=("embodied", "world-model", "planning", "test-time-scaling"),
        priority=1,
        benchmark_ids=("alfworld",),
        platform_pressure=("benchmark","evidence","execution/workflow","experimentation/study","model/request"),
        method_owned=("Convert raw visual observations into object-centric symbolic states.", "Propose candidate actions from current symbolic state and task goal.", "Predict Monte Carlo future states for candidate actions using temperature sampling.", "Rank imagined trajectories and refine the decision.", "Execute the selected action in ALFWorld.", "Condition the world model on new interaction history for unseen-environment adaptation."),
        platform_owned=("MethodProgram execution and Machine Journal truth","provider-independent model/tool dispatch and receipts","content-addressed benchmark task identity","Study/Experiment orchestration and measurement artifacts","run/evidence provenance and replay"),
    ),
    assets=(
        ReproductionAssetRef(ReproductionAssetKind.BENCHMARK,"research/reproductions/implement_acl2026/benchmark.py"),
        ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM,"research/reproductions/implement_acl2026/program.py"),
        ReproductionAssetRef(ReproductionAssetKind.STUDY,"research/reproductions/implement_acl2026/study.py"),
    ),
    primary_executable="research/reproductions/implement_acl2026/program.py",
    reported_results=(

    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="baseline_01",description="finetuning-based embodied agents"),
        ReferenceBaseline(baseline_id="baseline_02",description="ReAct"),
        ReferenceBaseline(baseline_id="baseline_03",description="Reflexion"),
        ReferenceBaseline(baseline_id="baseline_04",description="Self-consistency"),
        ReferenceBaseline(baseline_id="baseline_05",description="SimuRA"),
    ),
    blockers=("Matched execution requires the exact world-model checkpoint/training transitions and ALFWorld visual configuration.", "Final success-rate claims must be extracted from the final paper tables and reproduced with real model/environment runs."),
    evidence_refs=(),
    scientific_tests=("tests/test_scientific_frontier_2026_wave_01.py",),
)
__all__=["REPRODUCTION"]
