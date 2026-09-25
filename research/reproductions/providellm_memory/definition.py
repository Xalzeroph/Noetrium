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
    package="providellm_memory",
    lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(
        method_id="providellm",
        title="Streaming VideoLLMs for Real-Time Procedural Video Understanding",
        paper_uri=(
            "https://openaccess.thecvf.com/content/ICCV2025/html/"
            "Chatterjee_Streaming_VideoLLMs_for_Real-Time_Procedural_"
            "Video_Understanding_ICCV_2025_paper.html"
        ),
        year=2025,
        paper_revision="ICCV 2025 camera-ready",
    ),
    catalog=ReproductionCatalog(
        domains=("multimodal", "video", "memory", "streaming"),
        families=(
            "multimodal_memory",
            "streaming_video_memory",
            "interleaved_cache",
            "procedural_video_understanding",
        ),
        priority=1,
        benchmark_ids=("ego4d-goalstep",),
        platform_pressure=(
            "execution/machines/memory",
            "model/multimodal",
            "artifact/video",
            "benchmark/video",
            "experimentation/study",
        ),
        method_owned=(
            "verbalized long-term text memory",
            "DETR-QFormer short-term visual memory",
            "single-entry multimodal interleaved FIFO cache",
            "independent short-term and long-term exits",
            "tau-window duplicate suppression for verbalized observations",
        ),
        platform_owned=(
            "MemoryMachine journal authority",
            "multimodal provider execution",
            "artifact and evidence identity",
            "benchmark cut identity",
            "study and evaluation orchestration",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind.FIDELITY,
            path="research/reproductions/providellm_memory/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind.RESEARCH_PROGRAM,
            path="research/reproductions/providellm_memory/memory.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind.BENCHMARK,
            path="research/reproductions/providellm_memory/benchmark.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind.STUDY,
            path="research/reproductions/providellm_memory/study.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind.SUPPORT,
            path="research/reproductions/providellm_memory/source.py",
        ),
    ),
    primary_executable="research/reproductions/providellm_memory/memory.py",
    reported_results=(
        ReportedResult(
            claim_id="providellm_goalstep_val_map",
            metric_id="per_frame_map_percent",
            value=13.0,
            qualifiers={
                "benchmark": "ego4d-goalstep",
                "split": "val",
                "variant": "ProVideLLM-1B/5",
                "verbalization_and_interleaving": True,
                "short_term_seconds": 16,
                "long_term_seconds": 128,
                "source": "ICCV-2025 paper Table 1",
            },
        ),
        ReportedResult(
            claim_id="providellm_goalstep_test_map",
            metric_id="per_frame_map_percent",
            value=12.9,
            qualifiers={
                "benchmark": "ego4d-goalstep",
                "split": "test",
                "variant": "ProVideLLM-1B/5",
                "verbalization_and_interleaving": True,
                "source": "ICCV-2025 paper Table 1",
            },
        ),
        ReportedResult(
            claim_id="providellm_streaming_dialogue_fps",
            metric_id="streaming_fps",
            value=24.6,
            qualifiers={
                "variant": "ProVideLLM-1B/5",
                "mode": "streaming-dialogue",
                "hardware": "single-A6000",
                "source": "ICCV-2025 paper Table 9",
            },
        ),
        ReportedResult(
            claim_id="providellm_per_frame_full_model_fps",
            metric_id="streaming_fps",
            value=9.1,
            qualifiers={
                "variant": "ProVideLLM-1B/5",
                "mode": "per-frame",
                "hardware": "single-A6000",
                "source": "ICCV-2025 paper Table 9",
            },
        ),
        ReportedResult(
            claim_id="providellm_per_frame_gpu_memory",
            metric_id="gpu_memory_gb",
            value=2.0,
            qualifiers={
                "variant": "ProVideLLM-1B/5",
                "mode": "per-frame",
                "hardware": "single-A6000",
                "source": "ICCV-2025 paper Table 9",
            },
        ),
        ReportedResult(
            claim_id="providellm_one_hour_token_reduction",
            metric_id="token_reduction_factor",
            value=22.0,
            qualifiers={
                "horizon": "one-hour",
                "long_term_representation": "verbalized-text",
                "source": "ICCV-2025 abstract/runtime analysis",
            },
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id="providellm_no_verbalization",
            description=(
                "ProVideLLM-1B/5 without long-term verbalization on "
                "Ego4D Goal-Step online step detection."
            ),
            qualifiers={
                "val_per_frame_map_percent": 12.1,
                "test_per_frame_map_percent": 12.2,
                "source": "ICCV-2025 paper Table 1",
            },
        ),
        ReferenceBaseline(
            baseline_id="lstr_goalstep",
            description=(
                "LSTR long/short-term baseline on Ego4D Goal-Step online "
                "step detection."
            ),
            qualifiers={
                "val_per_frame_map_percent": 8.9,
                "test_per_frame_map_percent": 8.1,
                "source": "ICCV-2025 paper Table 1",
            },
        ),
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind.UNRESOLVED,
            description=(
                "The initial official release exposes DETR-QFormer and model "
                "training/evaluation code but explicitly does not release the "
                "verbalize-and-interleave streaming per-frame implementation. "
                "The MemoryProgram therefore implements Algorithms 1-2 from "
                "the ICCV paper rather than claiming official-code identity."
            ),
        ),
    ),
    blockers=(
        "Matched-result execution requires released checkpoint and licensed "
        "Ego4D Goal-Step video bytes under content-addressed artifact authority.",
        "Official streaming verbalize/interleave source remains unreleased in "
        "the audited initial repository release.",
        "The paper also evaluates EgoExo4D, COIN and Assembly101; those "
        "additional dataset/task authorities remain to be bound.",
    ),
    evidence_refs=(),
    scientific_tests=("tests/test_scientific_providellm_memory_v1.py",),
)


__all__ = ["REPRODUCTION"]
