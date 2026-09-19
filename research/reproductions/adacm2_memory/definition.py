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
    package="adacm2_memory",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="adacm2",
        title=(
            "AdaCM2: On Understanding Extremely Long-Term Video with "
            "Adaptive Cross-Modality Memory Reduction"
        ),
        paper_uri=(
            "https://openaccess.thecvf.com/content/CVPR2025/html/"
            "Man_AdaCM2_On_Understanding_Extremely_Long-Term_Video_"
            "with_Adaptive_Cross-Modality_Memory_CVPR_2025_paper.html"
        ),
        year=2025,
        paper_revision="CVPR 2025 camera-ready publication",
    ),
    catalog=ReproductionCatalog(
        domains=("multimodal", "video", "memory"),
        families=(
            "multimodal_memory",
            "long_video_understanding",
            "cross_modal_memory",
            "adaptive_kv_cache_reduction",
        ),
        priority=1,
        benchmark_ids=("lvu",),
        platform_pressure=(
            "execution/machines",
            "memory",
            "model/multimodal",
            "benchmark/video",
            "artifact/content",
            "experimentation/study",
        ),
        method_owned=(
            "regressive frame-by-frame Q-Former processing",
            "cross-modal attention token importance",
            "layer-wise K/V cache reduction",
            "recent-cache preservation",
            "previous-cache top-beta conservation",
            "alpha/beta cache partition and retention semantics",
        ),
        platform_owned=(
            "MemoryMachine journal authority",
            "multimodal tensor content identity",
            "cross-modal scorer implementation identity",
            "LVU full-video benchmark projection",
            "study and evaluation orchestration",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/adacm2_memory/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("research_program"),
            path="research/reproductions/adacm2_memory/memory.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("benchmark"),
            path="research/reproductions/adacm2_memory/benchmark.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("study"),
            path="research/reproductions/adacm2_memory/study.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/adacm2_memory/source.py",
        ),
    ),
    primary_executable="research/reproductions/adacm2_memory/memory.py",
    reported_results=(),
    reference_baselines=(),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description=(
                "The camera-ready paper's Eq.6 makes the previous cache an "
                "alpha fraction and the recent cache a (1-alpha) fraction, "
                "while Eq.8 states r=alpha+(1-alpha)*beta. Together with the "
                "text that retains all recent tokens and beta of previous "
                "tokens, these claims are algebraically inconsistent. "
                "Both eq6_literal and eq8_consistent treatments are exposed "
                "instead of silently choosing one interpretation."
            ),
        ),
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description=(
                "No author-maintained AdaCM2 executable repository was found "
                "during the source audit. Cross-modal attention scoring remains "
                "an explicit identity-bound paper port, while cache reduction "
                "itself is executable from the publication contract."
            ),
        ),
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description=(
                "The publication does not specify integer rounding when alpha "
                "or beta ratios produce fractional token counts. The executable "
                "contract records floor-min-one partitioning and ceil-min-one "
                "reserve rounding in the reduction-spec identity."
            ),
        ),
    ),
    blockers=(
        "Matched result reproduction requires official or authoritatively "
        "frozen AdaCM2 Q-Former weights and exact trained cross-modal scorer.",
        "Full LVU result reproduction requires the LVU 1.0 video/data bytes "
        "under content-addressed artifact authority.",
        "Breakfast, COIN, MSRVTT-QA, MSVD-QA, MSRVTT, MSVD and YouCook2 "
        "paper results require their own canonical benchmark cuts.",
    ),
    evidence_refs=(),
    scientific_tests=("tests/test_scientific_adacm2_memory_v1.py",),
)


__all__ = ["REPRODUCTION"]
