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
        benchmark_ids=(),
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
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/videollamb_memory/source.py",
        ),
    ),
    primary_executable="research/reproductions/videollamb_memory/memory.py",
    reported_results=(),
    reference_baselines=(),
    deltas=(),
    blockers=(
        "EgoSchema, NExT-QA, EgoPlan, MVBench and NIAVH benchmark cuts are not "
        "yet content-addressed in this package.",
        "The ICCV Study, released checkpoints and matched-result evidence are "
        "not yet bound.",
    ),
    evidence_refs=(),
    scientific_tests=("tests/test_scientific_videollamb_memory_v1.py",),
)


__all__ = ["REPRODUCTION"]
