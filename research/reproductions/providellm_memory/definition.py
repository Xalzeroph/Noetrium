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
    package="providellm_memory",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="providellm",
        title="Streaming VideoLLMs for Real-Time Procedural Video Understanding",
        paper_uri=(
            "https://openaccess.thecvf.com/content/ICCV2025/html/"
            "Chatterjee_Streaming_VideoLLMs_for_Real-Time_Procedural_"
            "Video_Understanding_ICCV_2025_paper.html"
        ),
        year=2025,
        paper_revision="ICCV 2025 camera-ready",
    ),
    catalog=ReproductionCatalog(
        domains=("multimodal", "video", "memory", "streaming"),
        families=(
            "multimodal_memory",
            "streaming_video_memory",
            "interleaved_cache",
            "procedural_video_understanding",
        ),
        priority=1,
        benchmark_ids=(),
        platform_pressure=(
            "execution/machines/memory",
            "model/multimodal",
            "artifact/video",
            "experimentation/study",
        ),
        method_owned=(
            "verbalized long-term text memory",
            "DETR-QFormer short-term visual memory",
            "single-entry multimodal interleaved FIFO cache",
            "independent short-term and long-term exits",
            "tau-window duplicate suppression for verbalized observations",
        ),
        platform_owned=(
            "MemoryMachine journal authority",
            "multimodal provider execution",
            "artifact and evidence identity",
            "benchmark cut identity",
            "study and evaluation orchestration",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/providellm_memory/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("research_program"),
            path="research/reproductions/providellm_memory/memory.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/providellm_memory/source.py",
        ),
    ),
    primary_executable="research/reproductions/providellm_memory/memory.py",
    reported_results=(),
    reference_baselines=(),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description=(
                "The initial official release exposes DETR-QFormer and model "
                "training/evaluation code but explicitly does not release the "
                "verbalize-and-interleave streaming per-frame implementation. "
                "The MemoryProgram therefore implements Algorithms 1-2 from "
                "the ICCV paper rather than claiming official-code identity."
            ),
        ),
    ),
    blockers=(
        "Formal benchmark cuts and ICCV Study bindings remain to be added.",
        "Matched-result reproduction requires released checkpoint and dataset "
        "bytes under content-addressed artifact authority.",
        "Official streaming verbalize/interleave source remains unreleased in "
        "the audited initial repository release.",
    ),
    evidence_refs=(),
    scientific_tests=("tests/test_scientific_providellm_memory_v1.py",),
)


__all__ = ["REPRODUCTION"]
