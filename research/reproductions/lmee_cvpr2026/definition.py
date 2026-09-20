from __future__ import annotations
from noetrium_platform.research.reproduction import ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef, ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle
REPRODUCTION=ReproductionDefinition(
    package="lmee_cvpr2026",lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="lmee_cvpr2026",title="Explore with Long-term Memory: A Benchmark and Multimodal LLM-based Reinforcement Learning Framework for Embodied Exploration",paper_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Wang_Explore_with_Long-term_Memory_A_Benchmark_and_Multimodal_LLM-based_Reinforcement_CVPR_2026_paper.html",year=2026,paper_revision="CVPR 2026 final proceedings"),
    catalog=ReproductionCatalog(domains=("agent","frontier-2026","embodied"),families=("embodied", "long-term-memory", "exploration", "reinforcement-learning", "multimodal"),priority=1,benchmark_ids=("lmee-bench",),platform_pressure=("benchmark","evidence","execution/workflow","experimentation/study","memory","model/request"),method_owned=("Observe the embodied scene and current long-term episodic memory.", "Retrieve task-relevant historical visual episodes and memory-based evidence.", "Plan exploration toward current navigation and memory-QA objectives.", "Execute the selected embodied exploration action.", "Append and consolidate new visual experience into long-term episodic memory.", "Answer memory-based questions when sufficient evidence exists or continue exploration."),platform_owned=("MethodProgram execution and Machine Journal truth","provider-independent model/tool dispatch and receipts","content-addressed benchmark task identity","Study/Experiment orchestration and measurement artifacts","run/evidence provenance and replay")),
    assets=(ReproductionAssetRef(ReproductionAssetKind.BENCHMARK,"research/reproductions/lmee_cvpr2026/benchmark.py"),ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM,"research/reproductions/lmee_cvpr2026/program.py"),ReproductionAssetRef(ReproductionAssetKind.STUDY,"research/reproductions/lmee_cvpr2026/study.py")),
    primary_executable="research/reproductions/lmee_cvpr2026/program.py",
    reported_results=(

    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="baseline_01",description="memory-free embodied explorer"),
        ReferenceBaseline(baseline_id="baseline_02",description="retrieval-only explorer"),
        ReferenceBaseline(baseline_id="baseline_03",description="paper embodied exploration baselines"),
    ),
    blockers=("Matched reproduction requires the released LMEE-Bench data, HM3D-Sem environment cut, MemoryExplorer checkpoint and training configuration.", "Training and interactive navigation claims require GPU/environment receipts and benchmark evaluator artifacts."),evidence_refs=(),scientific_tests=("tests/test_scientific_frontier_2026_wave_02.py",),
)
__all__=["REPRODUCTION"]
