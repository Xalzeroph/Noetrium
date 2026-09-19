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
    package="videoagent_memory",
    lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(
        method_id="videoagent-memory",
        title=(
            "VideoAgent: A Memory-augmented Multimodal Agent "
            "for Video Understanding"
        ),
        paper_uri=(
            "https://www.ecva.net/papers/eccv_2024/papers_ECCV/"
            "html/3241_ECCV_2024_paper.php"
        ),
        year=2024,
        paper_revision=(
            "ECCV 2024 / official executable commit "
            "02dbfd47732910a2e7348e47f695585d05178aba"
        ),
    ),
    catalog=ReproductionCatalog(
        domains=(
            "multimodal-memory",
            "video-understanding",
            "agentic-tool-use",
        ),
        families=(
            "multimodal_memory",
            "memory_augmented_agent",
            "video_agent",
            "react",
        ),
        priority=1,
        benchmark_ids=("egoschema",),
        platform_pressure=(
            "execution/machines/memory",
            "execution/workflow",
            "artifact/content",
            "model/multimodal",
            "model/embedding",
            "experimentation/study",
        ),
        method_owned=(
            "two-second temporal segment memory",
            "object-centric tracking/re-identification memory",
            "18:11 visual/textual segment-localization fusion",
            "top-level four-tool ReAct policy",
            "nested object-memory two-tool ReAct policy",
            "paper-era caption-range and early-stop quirks",
        ),
        platform_owned=(
            "MemoryMachine journal authority",
            "MethodProgram host and child-machine links",
            "content-addressed video/memory artifacts",
            "model and embedding provider transport",
            "benchmark cut authority",
            "measurement and study execution",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind.FIDELITY,
            path="research/reproductions/videoagent_memory/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind.RESEARCH_PROGRAM,
            path="research/reproductions/videoagent_memory/memory.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind.METHOD_PROGRAM,
            path="research/reproductions/videoagent_memory/program.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind.BENCHMARK,
            path="research/reproductions/videoagent_memory/benchmark.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind.STUDY,
            path="research/reproductions/videoagent_memory/study.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind.SUPPORT,
            path="research/reproductions/videoagent_memory/source.py",
        ),
    ),
    primary_executable="research/reproductions/videoagent_memory/program.py",
    reported_results=(),
    reference_baselines=(),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind.UNRESOLVED,
            description=(
                "The release uses a hosted GPT-4 service, but the exact "
                "paper-era model weights/service snapshot are not an immutable "
                "public artifact. Any current provider binding must therefore "
                "be recorded as a model substitution for numerical claims."
            ),
        ),
    ),
    blockers=(
        "A runnable study requires content-addressed EgoSchema video bytes and "
        "the VideoAgent preprocessing/model artifacts (ViCLIP, tracking, "
        "CLIP, DINOv2, Video-LLaVA).",
        "The exact paper-era hosted GPT-4 snapshot is not publicly immutable.",
        "The full 5031-question EgoSchema claim requires an official "
        "evaluation-server/Kaggle receipt; the 500-answer public cut is a "
        "separate offline evaluation.",
    ),
    evidence_refs=(),
    scientific_tests=(
        "tests/test_scientific_videoagent_memory_v1.py",
        "tests/test_scientific_videoagent_egoschema_v1.py",
    ),
)

__all__ = ["REPRODUCTION"]
