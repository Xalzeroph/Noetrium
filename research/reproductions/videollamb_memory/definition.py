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
    package="videollamb_memory",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="videollamb",
        title=(
            "VideoLLaMB: Long Streaming Video Understanding "
            "with Recurrent Memory Bridges"
        ),
        paper_uri=(
            "https://openaccess.thecvf.com/content/ICCV2025/html/"
            "Wang_VideoLLaMB_Long_Streaming_Video_Understanding_with_"
            "Recurrent_Memory_Bridges_ICCV_2025_paper.html"
        ),
        year=2025,
        paper_revision=(
            "ICCV 2025 camera-ready / official paper-era executable "
            "962837c5b310559de18b375eaee20561123bb54c"
        ),
    ),
    catalog=ReproductionCatalog(
        domains=("multimodal", "video", "memory", "streaming"),
        families=(
            "multimodal_memory",
            "recurrent_memory_bridge",
            "streaming_video_memory",
            "long_video_understanding",
        ),
        priority=1,
        benchmark_ids=("egoschema",),
        platform_pressure=(
            "execution/machines/memory",
            "model/multimodal",
            "artifact/tensor",
            "benchmark/video",
            "experimentation/study",
        ),
        method_owned=(
            "SceneTiling semantic video segmentation",
            "recurrent temporal memory tokens",
            "Transformer memory bridge update",
            "memory-cache cross-attention retrieval",
            "streaming semantic-segment recurrence",
        ),
        platform_owned=(
            "MemoryMachine journal authority",
            "immutable multimodal content identity",
            "model execution and transport",
            "benchmark cut identity",
            "artifact/evidence lineage",
            "study and evaluation orchestration",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/videollamb_memory/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("research_program"),
            path="research/reproductions/videollamb_memory/memory.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("benchmark"),
            path="research/reproductions/videollamb_memory/benchmark.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("study"),
            path="research/reproductions/videollamb_memory/study.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/videollamb_memory/source.py",
        ),
    ),
    primary_executable="research/reproductions/videollamb_memory/memory.py",
    reported_results=(
        ReportedResult(
            claim_id="videollamb_videoqa_gain",
            metric_id="average_gain_points",
            value=4.2,
            qualifiers={
                "scope": "four-videoqa-benchmarks",
                "source": "ICCV-2025 abstract",
            },
        ),
        ReportedResult(
            claim_id="videollamb_egocentric_planning_gain",
            metric_id="gain_points",
            value=2.06,
            qualifiers={
                "task": "egocentric-planning",
                "source": "ICCV-2025 abstract",
            },
        ),
        ReportedResult(
            claim_id="videollamb_single_a100_max_frames",
            metric_id="processed_frame_count",
            value=320,
            qualifiers={
                "hardware": "single-NVIDIA-A100",
                "training_frames": 16,
                "source": "ICCV-2025 abstract",
            },
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id="videollamb_paper_video_baselines",
            description=(
                "Existing VideoQA and egocentric-planning models used by the "
                "ICCV 2025 paper to establish the reported gains."
            ),
            qualifiers={"source": "ICCV-2025 paper evaluation"},
        ),
    ),
    deltas=(),
    blockers=(
        "NExT-QA, EgoPlan, MVBench and NIAVH benchmark cuts remain to be "
        "content-addressed alongside the bound EgoSchema public cut.",
        "Matched-result execution still requires the released checkpoint bytes "
        "and exact video assets in content-addressed authority.",
    ),
    evidence_refs=(),
    scientific_tests=("tests/test_scientific_videollamb_memory_v1.py",),
)


__all__ = ["REPRODUCTION"]
