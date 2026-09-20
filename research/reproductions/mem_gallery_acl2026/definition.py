from __future__ import annotations

from noetrium_platform.research.reproduction import (
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
    package="mem_gallery_acl2026",
    lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(
        method_id="mem_gallery_acl2026",
        title="Mem-Gallery: Benchmarking Multimodal Long-Term Conversational Memory for MLLM Agents",
        paper_uri="https://aclanthology.org/2026.acl-long.1892/",
        year=2026,
        paper_revision="ACL 2026 final proceedings",
    ),
    catalog=ReproductionCatalog(
        domains=("agent", "frontier-2026", "multimodal-memory"),
        families=("multimodal-memory", "benchmark", "conversation", "long-term-memory"),
        priority=1,
        benchmark_ids=("mem-gallery",),
        platform_pressure=("benchmark", "evidence", "execution/workflow", "experimentation/study", "model/request"),
        method_owned=("Replay the frozen multimodal multi-session conversation history.", "Evaluate memory extraction and test-time adaptation.", "Evaluate reasoning over cross-session multimodal memories.", "Evaluate organization and evolution of memory knowledge.", "Aggregate functional capability and efficiency measurements."),
        platform_owned=(
            "MethodProgram execution and Machine Journal truth",
            "provider-independent model/tool dispatch and receipts",
            "content-addressed benchmark task identity",
            "Study/Experiment orchestration and measurement artifacts",
            "run/evidence provenance and replay",
        ),
    ),
    assets=(
        ReproductionAssetRef(ReproductionAssetKind.BENCHMARK, "research/reproductions/mem_gallery_acl2026/benchmark.py"),
        ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM, "research/reproductions/mem_gallery_acl2026/program.py"),
        ReproductionAssetRef(ReproductionAssetKind.STUDY, "research/reproductions/mem_gallery_acl2026/study.py"),
    ),
    primary_executable="research/reproductions/mem_gallery_acl2026/program.py",
    reported_results=(
        ReportedResult(claim_id="mem_gallery_systems", metric_id="evaluated_memory_system_count", value=12, qualifiers={"source": "ACL 2026 final paper"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="baseline_01", description="twelve memory systems evaluated in the final ACL paper"),
    ),
    blockers=("Matched benchmarking requires the pinned Mem-Gallery dataset/scoring revision and model revisions.", "Multimodal inference results require real model receipts and retained media assets."),
    evidence_refs=(),
    scientific_tests=("tests/test_scientific_frontier_2026_wave_01.py",),
)

__all__ = ["REPRODUCTION"]
