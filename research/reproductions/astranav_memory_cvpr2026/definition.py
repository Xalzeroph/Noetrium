from __future__ import annotations
from noetrium_platform.research.reproduction import ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef, ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle
REPRODUCTION=ReproductionDefinition(
    package="astranav_memory_cvpr2026",lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="astranav_memory_cvpr2026",title="AstraNav-Memory: Contexts Compression for Long Memory",paper_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Hu_AstraNav-Memory_Contexts_Compression_for_Long_Memory_CVPR_2026_paper.html",year=2026,paper_revision="CVPR 2026 final proceedings"),
    catalog=ReproductionCatalog(domains=("agent","frontier-2026","embodied"),families=("embodied", "long-term-memory", "navigation", "visual-compression", "lifelong-agent"),priority=1,benchmark_ids=("goat-bench", "hm3d-ovon"),platform_pressure=("benchmark","evidence","execution/workflow","experimentation/study","memory","model/request","perception"),method_owned=("Acquire the current navigation image and task context.", "Compress the image through frozen DINOv3 features plus PixelUnshuffle/Conv visual tokenizer.", "Append compressed image tokens to the long-horizon image-centric memory context.", "Reason over current and historical compressed visual contexts with Qwen2.5-VL.", "Execute the next navigation action and preserve trajectory evidence."),platform_owned=("MethodProgram execution and Machine Journal truth","provider-independent model/tool dispatch and receipts","content-addressed benchmark task identity","Study/Experiment orchestration and measurement artifacts","run/evidence provenance and replay")),
    assets=(ReproductionAssetRef(ReproductionAssetKind.BENCHMARK,"research/reproductions/astranav_memory_cvpr2026/benchmark.py"),ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM,"research/reproductions/astranav_memory_cvpr2026/program.py"),ReproductionAssetRef(ReproductionAssetKind.STUDY,"research/reproductions/astranav_memory_cvpr2026/study.py")),
    primary_executable="research/reproductions/astranav_memory_cvpr2026/program.py",
    reported_results=(
        ReportedResult(claim_id="astranav_representative_compression",metric_id="compression_ratio",value=16,qualifiers={"unit": "x", "setting": "representative"}),
        ReportedResult(claim_id="astranav_tokens_per_image",metric_id="visual_tokens_per_frame",value=30,qualifiers={"unit": "tokens", "setting": "approximately"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="baseline_01",description="object-centric navigation memory"),
        ReferenceBaseline(baseline_id="baseline_02",description="short-context visual policy"),
        ReferenceBaseline(baseline_id="baseline_03",description="paper lifelong navigation baselines"),
    ),
    blockers=("Matched reproduction requires the pinned AstraNav checkpoints/training code and exact GOAT-Bench/HM3D-OVON releases.", "Navigation-efficiency claims require closed-loop simulator execution and path-metric receipts."),evidence_refs=(),scientific_tests=("tests/test_scientific_frontier_2026_wave_02.py",),
)
__all__=["REPRODUCTION"]
