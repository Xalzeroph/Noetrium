from __future__ import annotations

from noetrium_platform.research.reproduction import (
    ReproductionAssetKind,
    ReproductionAssetRef,
    ReproductionCatalog,
    ReproductionDefinition,
    ReproductionDelta,
    ReproductionDeltaKind,
    ReproductionIdentity,
    ReproductionLifecycle,
)


REPRODUCTION = ReproductionDefinition(
    package="worldmm_memory",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="worldmm",
        title=(
            "WorldMM: Dynamic Multimodal Memory Agent for "
            "Long Video Reasoning"
        ),
        paper_uri=(
            "https://openaccess.thecvf.com/content/CVPR2026/html/"
            "Yeo_WorldMM_Dynamic_Multimodal_Memory_Agent_for_Long_"
            "Video_Reasoning_CVPR_2026_paper.html"
        ),
        year=2026,
        paper_revision=(
            "CVPR 2026 camera-ready / official initial executable "
            "5a5f779026d51024746e7b3fab7959dd0beedcd7"
        ),
    ),
    catalog=ReproductionCatalog(
        domains=("multimodal", "video", "memory", "agent"),
        families=(
            "multimodal_memory",
            "long_video_understanding",
            "heterogeneous_memory",
            "agentic_retrieval",
            "episodic_semantic_visual_memory",
        ),
        priority=1,
        benchmark_ids=("egolifeqa",),
        platform_pressure=(
            "execution/machines/memory",
            "execution/workflow",
            "model/multimodal",
            "artifact/content",
            "benchmark/video",
            "experimentation/study",
        ),
        method_owned=(
            "episodic memory over 30sec/3min/10min/1h temporal scales",
            "HippoRAG candidate retrieval plus LLM multiscale reranking",
            "semantic entity-relation graph retrieval with Personalized PageRank",
            "visual clip similarity and timestamp-range frame retrieval",
            "cross-facet duplicate suppression",
            "iterative search-or-answer memory routing",
            "five-round and five-error stopping semantics",
        ),
        platform_owned=(
            "one MemoryMachine journal across heterogeneous memory facets",
            "MethodProgram and child-machine composition",
            "capability/model transport",
            "content-addressed multimodal artifacts",
            "benchmark cut identity",
            "study and evaluation orchestration",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/worldmm_memory/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("research_program"),
            path="research/reproductions/worldmm_memory/memory.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("method_program"),
            path="research/reproductions/worldmm_memory/program.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("benchmark"),
            path="research/reproductions/worldmm_memory/benchmark.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("study"),
            path="research/reproductions/worldmm_memory/study.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/worldmm_memory/source.py",
        ),
    ),
    primary_executable=(
        "research/reproductions/worldmm_memory/program.py"
    ),
    reported_results=(),
    reference_baselines=(),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description=(
                "The official repository's initial public executable is frozen "
                "as the primary source lane. A later 2025-12-24 commit explicitly "
                "repairs semantic-memory indexing; that repair is retained as a "
                "separate source lane rather than silently changing the initial "
                "executable semantics."
            ),
        ),
    ),
    blockers=(
        "Matched EgoLifeQA reproduction requires a canonical content-addressed "
        "EgoLife/EgoLifeQA data cut, multiscale caption files, semantic "
        "consolidation artifacts, and visual embeddings.",
        "Matched model behavior requires immutable identities for the retrieval "
        "and response models used by the evaluated configuration.",
    ),
    evidence_refs=(),
    scientific_tests=(
        "tests/test_scientific_worldmm_memory_v1.py",
        "tests/test_scientific_worldmm_egolifeqa_v1.py",
    ),
)


__all__ = ["REPRODUCTION"]
