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
    package="ma_lmm_memory",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="ma-lmm",
        title=(
            "MA-LMM: Memory-Augmented Large Multimodal Model for "
            "Long-Term Video Understanding"
        ),
        paper_uri=(
            "https://openaccess.thecvf.com/content/CVPR2024/html/"
            "He_MA-LMM_Memory-Augmented_Large_Multimodal_Model_for_"
            "Long-Term_Video_Understanding_CVPR_2024_paper.html"
        ),
        year=2024,
        paper_revision=(
            "CVPR 2024 / official initial implementation "
            "6ad50f3efcaca7776d2e1e5f1be32e09ceff9910"
        ),
    ),
    catalog=ReproductionCatalog(
        domains=("multimodal", "video", "memory"),
        families=(
            "multimodal_memory",
            "long_video_understanding",
            "online_memory",
            "memory_compression",
        ),
        priority=1,
        benchmark_ids=("lvu",),
        platform_pressure=(
            "execution/machines",
            "memory",
            "model/multimodal",
            "artifact/content",
            "experimentation/study",
        ),
        method_owned=(
            "online visual memory-bank update semantics",
            "query-memory attention history semantics",
            "per-token adjacent cosine merge selection",
            "compression-size-weighted memory consolidation",
        ),
        platform_owned=(
            "MemoryMachine journal authority",
            "multimodal content identity and transport",
            "model execution",
            "artifact/evidence lineage",
            "study and evaluation orchestration",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/ma_lmm_memory/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("research_program"),
            path="research/reproductions/ma_lmm_memory/memory.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("benchmark"),
            path="research/reproductions/ma_lmm_memory/benchmark.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("study"),
            path="research/reproductions/ma_lmm_memory/study.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/ma_lmm_memory/source.py",
        ),
    ),
    reported_results=(),
    reference_baselines=(),
    deltas=(),
    blockers=(
        "Full checkpoint-level CVPR result reproduction still requires frozen "
        "official model weights and acquisition of the LVU 1.0 video/data bytes "
        "into content-addressed artifact authority.",
        "The current executable pressure target isolates the paper memory "
        "algorithm from the surrounding LAVIS/Vicuna tensor stack.",
    ),
    evidence_refs=(),
    scientific_tests=(
        "tests/test_scientific_ma_lmm_memory_v1.py",
    ),
)


__all__ = ["REPRODUCTION"]
