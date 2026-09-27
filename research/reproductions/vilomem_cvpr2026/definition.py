from __future__ import annotations
from research.reproductions.contracts import ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef, ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle
REPRODUCTION=ReproductionDefinition(
    package="vilomem_cvpr2026",lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="vilomem_cvpr2026",title="ViLoMem: Agentic Learner with Grow-and-Refine Multimodal Semantic Memory",paper_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Bo_ViLoMem_Agentic_Learner_with_Grow-and-Refine_Multimodal_Semantic_Memory_CVPR_2026_paper.html",year=2026,paper_revision="CVPR 2026 final proceedings"),
    catalog=ReproductionCatalog(domains=("agent","frontier-2026","multimodal-memory"),families=("multimodal-memory", "semantic-memory", "lifelong-learning", "error-attribution", "agentic-learning"),priority=1,benchmark_ids=("mmmu", "mathvista", "mathvision", "hallusionbench", "mmstar", "realworldqa"),platform_pressure=("artifact/lineage","benchmark","evidence","execution/workflow","experimentation/study","memory","model/request","perception"),method_owned=("Solve the multimodal query using retrieved logical and visual semantic memories.", "Verify the prediction and identify whether the attempt should contribute new memory.", "Attribute reasoning failures into structured logical error and strategy schemas.", "Analyze attention/perception failures and isolate visual distraction or hallucination patterns.", "Merge with a similar memory schema or create a new schema while preserving stable reusable knowledge.", "Retrieve logical memories by problem/text similarity and visual memories by image embedding plus query filtering."),platform_owned=("MethodProgram execution and Machine Journal truth","provider-independent model/tool dispatch and receipts","content-addressed benchmark task identity","Study/Experiment orchestration and measurement artifacts","run/evidence provenance and replay")),
    assets=(ReproductionAssetRef(ReproductionAssetKind.BENCHMARK,"research/reproductions/vilomem_cvpr2026/benchmark.py"),ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM,"research/reproductions/vilomem_cvpr2026/program.py"),ReproductionAssetRef(ReproductionAssetKind.STUDY,"research/reproductions/vilomem_cvpr2026/study.py")),
    primary_executable="research/reproductions/vilomem_cvpr2026/program.py",
    reported_results=(
        ReportedResult(claim_id="vilomem_gpt41_mmmu",metric_id="pass_at_1",value=77.26,qualifiers={"benchmark": "MMMU", "model": "GPT-4.1", "unit": "percent"}),
        ReportedResult(claim_id="vilomem_gpt41_mathvista",metric_id="pass_at_1",value=76.88,qualifiers={"benchmark": "MathVista", "model": "GPT-4.1", "unit": "percent"}),
        ReportedResult(claim_id="vilomem_gpt41_mathvision",metric_id="pass_at_1",value=53.95,qualifiers={"benchmark": "MathVision", "model": "GPT-4.1", "unit": "percent"}),
        ReportedResult(claim_id="vilomem_gpt41_hallusion",metric_id="pass_at_1",value=75.29,qualifiers={"benchmark": "HallusionBench", "model": "GPT-4.1", "unit": "percent"}),
        ReportedResult(claim_id="vilomem_gpt41_mmstar",metric_id="pass_at_1",value=72.43,qualifiers={"benchmark": "MMStar", "model": "GPT-4.1", "unit": "percent"}),
        ReportedResult(claim_id="vilomem_gpt41_realworldqa",metric_id="pass_at_1",value=74.38,qualifiers={"benchmark": "RealWorldQA", "model": "GPT-4.1", "unit": "percent"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="baseline_01",description="no-memory baseline"),
        ReferenceBaseline(baseline_id="baseline_02",description="step-by-step baseline"),
        ReferenceBaseline(baseline_id="baseline_03",description="Dynamic-Cheatsheet"),
        ReferenceBaseline(baseline_id="baseline_04",description="attention-augmented variants"),
    ),
    blockers=("Matched reproduction requires the paper-ready ViLoMem source cut, exact VLMEvalKit dataset revisions, model-provider snapshots and attention-map configuration.", "Cross-benchmark/cross-model transfer claims require immutable memory-schema artifacts and source-run lineage rather than reusing opaque mutable memory directories."),evidence_refs=(),scientific_tests=('tests/test_scientific_reproduction_current_surface_v1.py',),
)
__all__=["REPRODUCTION"]
