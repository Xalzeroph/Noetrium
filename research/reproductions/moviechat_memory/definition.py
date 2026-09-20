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
    package="moviechat_memory",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="moviechat",
        title=(
            "MovieChat: From Dense Token to Sparse Memory for "
            "Long Video Understanding"
        ),
        paper_uri=(
            "https://openaccess.thecvf.com/content/CVPR2024/html/"
            "Song_MovieChat_From_Dense_Token_to_Sparse_Memory_for_"
            "Long_Video_CVPR_2024_paper.html"
        ),
        year=2024,
        paper_revision=(
            "CVPR 2024 / paper-era core executable "
            "f73f49233ea315bddc659ab3d1e358e0130eadb7"
        ),
    ),
    catalog=ReproductionCatalog(
        domains=("multimodal", "video", "memory"),
        families=(
            "multimodal_memory",
            "long_video_understanding",
            "short_long_memory",
            "sparse_memory",
        ),
        priority=1,
        benchmark_ids=("moviechat-1k",),
        platform_pressure=(
            "execution/machines",
            "memory",
            "model/multimodal",
            "benchmark/video",
            "artifact/content",
            "experimentation/study",
        ),
        method_owned=(
            "short-term FIFO buffer semantics",
            "short-term adjacent-frame consolidation",
            "long-term sparse memory semantics",
            "global versus breakpoint memory readout",
            "source-faithful direct-LTM consolidation quirk",
        ),
        platform_owned=(
            "MemoryMachine journal authority",
            "multimodal content identity and transport",
            "model execution",
            "benchmark materialization",
            "artifact/evidence lineage",
            "study and evaluation orchestration",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/moviechat_memory/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("research_program"),
            path="research/reproductions/moviechat_memory/memory.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("benchmark"),
            path="research/reproductions/moviechat_memory/benchmark.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("study"),
            path="research/reproductions/moviechat_memory/study.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/moviechat_memory/source.py",
        ),
    ),
    reported_results=(
        ReportedResult(
            claim_id="moviechat_global_accuracy",
            metric_id="open_ended_accuracy_percent",
            value=67.8,
            qualifiers={
                "benchmark": "moviechat-1k",
                "mode": "global",
                "evaluator": "gpt-3.5",
                "source": "CVPR-2024 supplementary Table H5",
            },
        ),
        ReportedResult(
            claim_id="moviechat_global_score",
            metric_id="open_ended_quality_score_0_to_5",
            value=3.81,
            qualifiers={
                "benchmark": "moviechat-1k",
                "mode": "global",
                "evaluator": "gpt-3.5",
                "source": "CVPR-2024 supplementary Table H5",
            },
        ),
        ReportedResult(
            claim_id="moviechat_breakpoint_accuracy",
            metric_id="open_ended_accuracy_percent",
            value=50.4,
            qualifiers={
                "benchmark": "moviechat-1k",
                "mode": "breakpoint",
                "evaluator": "gpt-3.5",
                "source": "CVPR-2024 supplementary Table H5",
            },
        ),
        ReportedResult(
            claim_id="moviechat_breakpoint_score",
            metric_id="open_ended_quality_score_0_to_5",
            value=2.96,
            qualifiers={
                "benchmark": "moviechat-1k",
                "mode": "breakpoint",
                "evaluator": "gpt-3.5",
                "source": "CVPR-2024 supplementary Table H5",
            },
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id="videochat_moviechat1k",
            description="VideoChat baseline reported in the MovieChat-1K comparison.",
            qualifiers={
                "global_accuracy_percent": 61.0,
                "global_score_0_to_5": 3.34,
                "source": "CVPR-2024 supplementary evaluation",
            },
        ),
    ),
    deltas=(),
    blockers=(
        "Full result reproduction requires acquisition of the official "
        "MovieChat-1K test video/QA bytes and released model weights into "
        "content-addressed artifact authority.",
        "The executable source and the paper differ in one direct-LTM pair "
        "selection detail; both identities are preserved rather than silently "
        "normalizing the implementation to the paper description.",
    ),
    evidence_refs=(),
    scientific_tests=(
        "tests/test_scientific_moviechat_memory_v1.py",
    ),
)


__all__ = ["REPRODUCTION"]
