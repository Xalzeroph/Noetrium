from __future__ import annotations
from noetrium_platform.research.reproduction import ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef, ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle
REPRODUCTION=ReproductionDefinition(
    package="orbit_acl2026",
    lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="orbit_acl2026",title="On-policy Reinforcement Fine-tuning with Offline reward for Multi-step Embodied Planning",paper_uri="https://aclanthology.org/2026.acl-long.1822/",year=2026,paper_revision="ACL 2026 final proceedings"),
    catalog=ReproductionCatalog(
        domains=("agent","frontier-2026","embodied"),
        families=("embodied", "planning", "reinforcement-learning", "multimodal"),
        priority=1,
        benchmark_ids=("embodiedbench",),
        platform_pressure=("benchmark","evidence","execution/workflow","experimentation/study","model/request"),
        method_owned=("Collect on-policy multi-step embodied planning trajectories.", "Score collected trajectories with the paper's offline reward mechanism.", "Apply reinforcement fine-tuning using offline reward.", "Evaluate in-domain EB-ALFRED tasks.", "Evaluate unseen EB-Habitat tasks."),
        platform_owned=("MethodProgram execution and Machine Journal truth","provider-independent model/tool dispatch and receipts","content-addressed benchmark task identity","Study/Experiment orchestration and measurement artifacts","run/evidence provenance and replay"),
    ),
    assets=(
        ReproductionAssetRef(ReproductionAssetKind.BENCHMARK,"research/reproductions/orbit_acl2026/benchmark.py"),
        ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM,"research/reproductions/orbit_acl2026/program.py"),
        ReproductionAssetRef(ReproductionAssetKind.STUDY,"research/reproductions/orbit_acl2026/study.py"),
    ),
    primary_executable="research/reproductions/orbit_acl2026/program.py",
    reported_results=(
        ReportedResult(claim_id="orbit_eb_alfred_seen",metric_id="task_success",value=72.4,qualifiers={"benchmark": "EB-ALFRED", "setting": "SFT+RFT", "model": "Qwen2.5-VL-7B"}),
        ReportedResult(claim_id="orbit_eb_habitat_unseen",metric_id="task_success",value=22.4,qualifiers={"benchmark": "EB-Habitat", "setting": "SFT+RFT", "model": "Qwen2.5-VL-7B"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="baseline_01",description="base Qwen2.5-VL-7B planner"),
        ReferenceBaseline(baseline_id="baseline_02",description="closed-source MLLMs"),
        ReferenceBaseline(baseline_id="baseline_03",description="WAP-7B"),
        ReferenceBaseline(baseline_id="baseline_04",description="ERA-7B"),
        ReferenceBaseline(baseline_id="baseline_05",description="VAGEN-3B"),
    ),
    blockers=("Matched execution requires the pinned ORBIT code/training configuration and EmbodiedBench release.", "Training-efficiency and generalization claims require GPU training plus interactive environment receipts."),
    evidence_refs=(),
    scientific_tests=("tests/test_scientific_frontier_2026_wave_01.py",),
)
__all__=["REPRODUCTION"]
