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
        benchmark_ids=(),
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
    ),
    reported_results=(),
    reference_baselines=(),
    deltas=(),
    blockers=(
        "The paper-native tree-search MethodProgram and fixed-size memory "
        "program are not yet bound.",
        "EgoSchema, LVBench, MMBench-Video and Video-MME benchmark cuts are "
        "not yet content-addressed in this package.",
        "The ICCV evaluation Study and executable model/provider bindings "
        "remain to be implemented.",
    ),
    evidence_refs=(),
    scientific_tests=("tests/test_scientific_vca_video_v1.py",),
)


__all__ = ["REPRODUCTION"]
