from __future__ import annotations

from noetrium_platform.research.reproduction import (
    ReproductionAssetKind,
    ReproductionAssetRef,
    ReproductionCatalog,
    ReproductionDefinition,
    ReproductionIdentity,
    ReproductionLifecycle,
)


REPRODUCTION = ReproductionDefinition(
    package="vca_video",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="vca-video",
        title="VCA: Video Curious Agent for Long Video Understanding",
        paper_uri=(
            "https://openaccess.thecvf.com/content/ICCV2025/html/"
            "Yang_VCA_Video_Curious_Agent_for_Long_Video_Understanding_"
            "ICCV_2025_paper.html"
        ),
        year=2025,
        paper_revision="ICCV 2025 camera-ready",
    ),
    catalog=ReproductionCatalog(
        domains=("multimodal", "video", "agent", "memory", "search"),
        families=(
            "long_video_understanding",
            "active_video_exploration",
            "curiosity_driven_search",
            "multimodal_memory",
        ),
        priority=1,
        benchmark_ids=("egoschema",),
        platform_pressure=(
            "execution/machines/method",
            "execution/machines/memory",
            "model/multimodal",
            "benchmark/video",
            "experimentation/study",
        ),
        method_owned=(
            "tree-structured video-segment exploration",
            "VLM self-generated intrinsic reward",
            "reward-history-conditioned exploration",
            "fixed-size selected-frame memory",
            "non-greedy temperature-controlled segment choice",
        ),
        platform_owned=(
            "MethodMachine and MemoryMachine journal authority",
            "multimodal model transport",
            "benchmark cut identity",
            "artifact/evidence lineage",
            "study and evaluation orchestration",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/vca_video/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("method_program"),
            path="research/reproductions/vca_video/program.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("study"),
            path="research/reproductions/vca_video/study.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/vca_video/source.py",
        ),
    ),
    primary_executable="research/reproductions/vca_video/program.py",
    reported_results=(),
    reference_baselines=(),
    deltas=(),
    blockers=(
        "LVBench, MMBench-Video and Video-MME benchmark cuts remain to be "
        "content-addressed alongside the bound EgoSchema public cut.",
        "Matched-result execution still requires the released multimodal "
        "model/provider binding and exact video assets.",
    ),
    evidence_refs=(),
    scientific_tests=("tests/test_scientific_vca_video_v1.py",),
)


__all__ = ["REPRODUCTION"]
