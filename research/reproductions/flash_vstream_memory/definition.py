from __future__ import annotations

from research.reproductions.contracts import (
    ReferenceBaseline,
    ReportedResult,
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
    lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
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
        benchmark_ids=("egoschema",),
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
            kind=ReproductionAssetKind.FIDELITY,
            path="research/reproductions/flash_vstream_memory/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind.RESEARCH_PROGRAM,
            path="research/reproductions/flash_vstream_memory/memory.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind.BENCHMARK,
            path="research/reproductions/flash_vstream_memory/benchmark.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind.STUDY,
            path="research/reproductions/flash_vstream_memory/study.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind.SUPPORT,
            path="research/reproductions/flash_vstream_memory/source.py",
        ),
    ),
    primary_executable="research/reproductions/flash_vstream_memory/memory.py",
    reported_results=(
        ReportedResult(
            claim_id="flash_vstream_egoschema_main",
            metric_id="multiple_choice_accuracy_percent",
            value=68.2,
            qualifiers={
                "benchmark": "egoschema",
                "configuration": "CSM+DAM",
                "visual_tokens": 11520,
                "source": "ICCV-2025 paper memory-component ablation",
            },
        ),
        ReportedResult(
            claim_id="flash_vstream_mvbench_main",
            metric_id="multiple_choice_accuracy_percent",
            value=65.4,
            qualifiers={
                "benchmark": "mvbench",
                "configuration": "CSM+DAM",
                "visual_tokens": 11520,
                "source": "ICCV-2025 paper memory-component ablation",
            },
        ),
        ReportedResult(
            claim_id="flash_vstream_video_mme_without_subtitles_main",
            metric_id="multiple_choice_accuracy_percent",
            value=61.2,
            qualifiers={
                "benchmark": "video-mme",
                "subtitles": False,
                "configuration": "CSM+DAM",
                "visual_tokens": 11520,
                "source": "ICCV-2025 paper memory-component ablation",
            },
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id="flash_vstream_csm_only",
            description=(
                "Flash-VStream ablation retaining context memory while "
                "removing augmentation memory."
            ),
            qualifiers={
                "egoschema_accuracy_percent": 66.8,
                "mvbench_accuracy_percent": 64.0,
                "video_mme_without_subtitles_accuracy_percent": 60.1,
                "visual_tokens": 3840,
                "source": "ICCV-2025 paper memory-component ablation",
            },
        ),
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind.UNRESOLVED,
            description=(
                "The official repository contains a 2024 LLaVA precursor and the "
                "2025 Qwen implementation released with the ICCV version. "
                "They remain separate source lanes; the precursor is not "
                "treated as the ICCV executable."
            ),
        ),
    ),
    blockers=(
        "Matched numerical execution requires content-addressed EgoSchema video "
        "bytes plus exact released Qwen2-VL/Flash-VStream checkpoint assets.",
        "The paper also reports MLVU, LVBench, MVBench and Video-MME; those "
        "additional benchmark authorities remain to be bound.",
        "A full end-to-end inference MethodProgram remains to be separated from "
        "the already bound dual Flash MemoryProgram.",
    ),
    evidence_refs=(),
    scientific_tests=("tests/test_scientific_flash_vstream_memory_v1.py",),
)


__all__ = ["REPRODUCTION"]
