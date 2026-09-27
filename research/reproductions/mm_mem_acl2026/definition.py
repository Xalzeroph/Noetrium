from __future__ import annotations

from research.reproductions.contracts import (
    ReferenceBaseline,
    ReportedResult,
    ReproductionAssetKind,
    ReproductionAssetRef,
    ReproductionCatalog,
    ReproductionDefinition,
    ReproductionIdentity,
    ReproductionLifecycle,
)

REPRODUCTION = ReproductionDefinition(
    package="mm_mem_acl2026",
    lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(
        method_id="mm_mem_acl2026",
        title="From Verbatim to Gist: Distilling Pyramidal Multimodal Memory via Semantic Information Bottleneck for Long-Horizon Video Agents",
        paper_uri="https://aclanthology.org/2026.acl-long.533/",
        year=2026,
        paper_revision="ACL 2026 final proceedings",
    ),
    catalog=ReproductionCatalog(
        domains=("agent", "frontier-2026", "multimodal-memory"),
        families=("multimodal-memory", "video-agent", "long-horizon", "reinforcement-learning"),
        priority=1,
        benchmark_ids=("video-mme", "hd-epic", "mlvu", "vstream-qa"),
        platform_pressure=("benchmark", "evidence", "execution/workflow", "experimentation/study", "model/request"),
        method_owned=("Encode incoming visual evidence into fine-grained sensory traces.", "Distill sensory traces into an episodic stream while preserving task-relevant evidence.", "Compress episodic evidence into high-level symbolic gist schemas.", "Choose ADD_NEW, MERGE, or DISCARD under the Semantic Information Bottleneck objective.", "Retrieve memory top-down using entropy-driven adaptive selection.", "Answer the video query from retrieved multimodal memory."),
        platform_owned=(
            "MethodProgram execution and Machine Journal truth",
            "provider-independent model/tool dispatch and receipts",
            "content-addressed benchmark task identity",
            "Study/Experiment orchestration and measurement artifacts",
            "run/evidence provenance and replay",
        ),
    ),
    assets=(
        ReproductionAssetRef(ReproductionAssetKind.BENCHMARK, "research/reproductions/mm_mem_acl2026/benchmark.py"),
        ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM, "research/reproductions/mm_mem_acl2026/program.py"),
        ReproductionAssetRef(ReproductionAssetKind.STUDY, "research/reproductions/mm_mem_acl2026/study.py"),
    ),
    primary_executable="research/reproductions/mm_mem_acl2026/program.py",
    reported_results=(
        ReportedResult(claim_id="mm_mem_videomme_subtitles", metric_id="qa_accuracy", value=78.1, qualifiers={"benchmark": "Video-MME", "setting": "with subtitles", "source": "ACL 2026 paper ablation/main results"}),
        ReportedResult(claim_id="mm_mem_vstream_ego", metric_id="qa_accuracy", value=62.5, qualifiers={"benchmark": "VStream-QA-Ego", "source": "ACL 2026 paper"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="baseline_01", description="dense visual memory"),
        ReferenceBaseline(baseline_id="baseline_02", description="text-centric caption memory"),
        ReferenceBaseline(baseline_id="baseline_03", description="Flash-VStream"),
        ReferenceBaseline(baseline_id="baseline_04", description="Qwen3-VL-8B"),
    ),
    blockers=("Matched execution requires the pinned MM-Mem code/checkpoint and exact four benchmark media cuts.", "Long-video claims require GPU inference receipts and benchmark evaluator artifacts."),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_frontier_2026_wave_01.py',),
)

__all__ = ["REPRODUCTION"]
