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
    reported_results=(
        ReportedResult(
            claim_id="vca_egoschema_accuracy",
            metric_id="multiple_choice_accuracy_percent",
            value=73.6,
            qualifiers={
                "benchmark": "egoschema",
                "average_frames": 7.2,
                "source": "ICCV-2025 paper evaluation",
            },
        ),
        ReportedResult(
            claim_id="vca_egoschema_average_frames",
            metric_id="average_selected_frame_count",
            value=7.2,
            qualifiers={
                "benchmark": "egoschema",
                "accuracy_percent": 73.6,
                "source": "ICCV-2025 paper evaluation",
            },
        ),
        ReportedResult(
            claim_id="vca_lvbench_accuracy",
            metric_id="multiple_choice_accuracy_percent",
            value=41.3,
            qualifiers={
                "benchmark": "lvbench",
                "average_frames": 20.0,
                "source": "ICCV-2025 paper evaluation",
            },
        ),
        ReportedResult(
            claim_id="vca_lvbench_average_frames",
            metric_id="average_selected_frame_count",
            value=20.0,
            qualifiers={
                "benchmark": "lvbench",
                "accuracy_percent": 41.3,
                "source": "ICCV-2025 paper evaluation",
            },
        ),
        ReportedResult(
            claim_id="vca_egoschema_uniform_gain",
            metric_id="accuracy_gain_points",
            value=3.2,
            qualifiers={
                "benchmark": "egoschema",
                "comparison": "uniform-frame-gpt-4o",
                "frame_budget": "less-than-30-percent",
                "source": "ICCV-2025 paper analysis",
            },
        ),
        ReportedResult(
            claim_id="vca_lvbench_uniform_gain",
            metric_id="accuracy_gain_points",
            value=6.6,
            qualifiers={
                "benchmark": "lvbench",
                "comparison": "uniform-frame-gpt-4o",
                "frame_budget": "less-than-30-percent",
                "source": "ICCV-2025 paper analysis",
            },
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id="vca_uniform_frame_gpt4o",
            description=(
                "Uniform-frame GPT-4o baseline used to measure the gain from "
                "curiosity-driven active video exploration."
            ),
            qualifiers={"source": "ICCV-2025 paper evaluation"},
        ),
    ),
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
