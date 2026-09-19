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
    package="flash_vstream_memory",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="flash-vstream",
        title=(
            "Flash-VStream: Efficient Real-Time Understanding "
            "for Long Video Streams"
        ),
        paper_uri=(
            "https://openaccess.thecvf.com/content/ICCV2025/html/"
            "Zhang_Flash-VStream_Efficient_Real-Time_Understanding_"
            "for_Long_Video_Streams_ICCV_2025_paper.html"
        ),
        year=2025,
        paper_revision=(
            "ICCV 2025 camera-ready / official Qwen executable "
            "6a82abfeac43012731610f27946d7ab2e86d6f8c"
        ),
    ),
    catalog=ReproductionCatalog(
        domains=("multimodal", "video", "memory", "streaming"),
        families=(
            "multimodal_memory",
            "long_video_understanding",
            "streaming_video_memory",
            "dual_flash_memory",
        ),
        priority=1,
        benchmark_ids=(),
        platform_pressure=(
            "execution/machines/memory",
            "model/multimodal",
            "artifact/tensor",
            "benchmark/video",
            "experimentation/study",
        ),
        method_owned=(
            "context-memory temporal compression",
            "augmentation-memory high-resolution retrieval",
            "augmentation conditioned on context-memory centroids",
            "memory-aware rotary-position semantics",
            "augmentation-before-context memory composition",
        ),
        platform_owned=(
            "MemoryMachine journal authority",
            "immutable tensor content references",
            "multimodal model transport",
            "benchmark cut identity",
            "study and evaluation orchestration",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/flash_vstream_memory/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("research_program"),
            path="research/reproductions/flash_vstream_memory/memory.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/flash_vstream_memory/source.py",
        ),
    ),
    reported_results=(),
    reference_baselines=(),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description=(
                "The official repository contains a 2024 LLaVA precursor and the "
                "2025 Qwen implementation released with the ICCV version. "
                "They remain separate source lanes; the precursor is not "
                "treated as the ICCV executable."
            ),
        ),
    ),
    blockers=(
        "The current package binds the dual Flash MemoryProgram but has not "
        "yet bound the paper inference MethodProgram.",
        "Matched result reproduction requires content-addressed benchmark "
        "video/annotation cuts and the exact released model/checkpoint assets.",
        "Benchmark and study protocols are not yet bound in this package.",
    ),
    evidence_refs=(),
    scientific_tests=("tests/test_scientific_flash_vstream_memory_v1.py",),
)


__all__ = ["REPRODUCTION"]
