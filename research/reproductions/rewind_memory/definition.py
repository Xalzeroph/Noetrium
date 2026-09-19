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
    package="rewind_memory",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="rewind",
        title="ReWind: Understanding Long Videos with Instructed Learnable Memory",
        paper_uri=(
            "https://openaccess.thecvf.com/content/CVPR2025/html/"
            "Diko_ReWind_Understanding_Long_Videos_with_"
            "Instructed_Learnable_Memory_CVPR_2025_paper.html"
        ),
        year=2025,
        paper_revision="CVPR 2025 camera-ready publication",
    ),
    catalog=ReproductionCatalog(
        domains=("multimodal", "video", "memory"),
        families=(
            "multimodal_memory",
            "long_video_understanding",
            "instruction_conditioned_memory",
            "dynamic_frame_selection",
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
            "learned read-perceive-write memory cycle",
            "instruction-conditioned memory interaction",
            "two-token-per-frame temporal memory",
            "instruction-attention first-stage frame selection",
            "DPC-KNN representative-frame selection",
            "memory plus high-resolution frame LLM input ordering",
        ),
        platform_owned=(
            "MemoryMachine journal authority",
            "multimodal tensor content identity",
            "learned operator/model binding identity",
            "benchmark materialization",
            "study and evaluation orchestration",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/rewind_memory/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("research_program"),
            path="research/reproductions/rewind_memory/memory.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("benchmark"),
            path="research/reproductions/rewind_memory/benchmark.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("study"),
            path="research/reproductions/rewind_memory/study.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/rewind_memory/source.py",
        ),
    ),
    primary_executable="research/reproductions/rewind_memory/memory.py",
    reported_results=(),
    reference_baselines=(),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description=(
                "No author-maintained ReWind executable repository was found "
                "during the source audit. The executable reproduction is "
                "therefore derived from the CVPR 2025 camera-ready method "
                "contract, and learned read/write/DFS operators remain explicit "
                "identity-bound ports rather than fabricated implementations."
            ),
        ),
    ),
    blockers=(
        "Matched checkpoint-level reproduction requires official or otherwise "
        "authoritatively frozen ReWind weights and learned operator parameters.",
        "Full result reproduction requires acquisition of MovieChat-1K video/QA "
        "bytes and the exact evaluation/model-serving artifacts under content "
        "identity.",
        "Charades-STA temporal-grounding result reproduction requires a separate "
        "canonical Charades-STA benchmark cut and the paper fine-tuning assets.",
    ),
    evidence_refs=(),
    scientific_tests=("tests/test_scientific_rewind_memory_v1.py",),
)


__all__ = ["REPRODUCTION"]
