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
    package="drvideo",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="drvideo",
        title="DrVideo: Document Retrieval Based Long Video Understanding",
        paper_uri=(
            "https://openaccess.thecvf.com/content/CVPR2025/html/"
            "Ma_DrVideo_Document_Retrieval_Based_Long_Video_"
            "Understanding_CVPR_2025_paper.html"
        ),
        year=2025,
        paper_revision="CVPR 2025 camera-ready",
    ),
    catalog=ReproductionCatalog(
        domains=("multimodal", "video", "agent", "retrieval"),
        families=(
            "long_video_understanding",
            "document_retrieval",
            "iterative_video_agent",
            "question_conditioned_augmentation",
        ),
        priority=1,
        benchmark_ids=("egoschema",),
        platform_pressure=(
            "execution/machines/method",
            "data/semantic-similarity",
            "model/multimodal",
            "benchmark/video",
            "experimentation/study",
        ),
        method_owned=(
            "video-to-text long-document construction",
            "question-to-document semantic frame retrieval",
            "question-conditioned key-frame augmentation",
            "planning-agent sufficiency judgement",
            "interaction-agent adaptive frame/type selection",
            "two-round document augmentation loop",
            "final chain-of-thought answer generation",
        ),
        platform_owned=(
            "MethodMachine journal authority",
            "semantic-similarity capability execution",
            "multimodal model transport",
            "artifact/evidence lineage",
            "benchmark cut identity",
            "study and evaluation orchestration",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/drvideo/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("benchmark"),
            path="research/reproductions/drvideo/benchmark.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("method_program"),
            path="research/reproductions/drvideo/program.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("study"),
            path="research/reproductions/drvideo/study.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/drvideo/source.py",
        ),
    ),
    primary_executable="research/reproductions/drvideo/program.py",
    reported_results=(
        ReportedResult(
            claim_id="drvideo_egoschema_public_gpt4",
            metric_id="multiple_choice_accuracy_percent",
            value=66.4,
            qualifiers={
                "benchmark": "egoschema",
                "split": "public-500",
                "model": "gpt-4-1106-preview",
                "source": "CVPR-2025 paper Table 1",
            },
        ),
        ReportedResult(
            claim_id="drvideo_egoschema_full_gpt4",
            metric_id="multiple_choice_accuracy_percent",
            value=61.0,
            qualifiers={
                "benchmark": "egoschema",
                "split": "full-5031",
                "model": "gpt-4-1106-preview",
                "source": "CVPR-2025 paper Table 1",
            },
        ),
        ReportedResult(
            claim_id="drvideo_moviechat_global_accuracy",
            metric_id="open_ended_accuracy_percent",
            value=93.1,
            qualifiers={
                "benchmark": "moviechat-1k",
                "mode": "global",
                "source": "CVPR-2025 paper evaluation",
            },
        ),
        ReportedResult(
            claim_id="drvideo_moviechat_global_score",
            metric_id="open_ended_quality_score_0_to_5",
            value=4.41,
            qualifiers={
                "benchmark": "moviechat-1k",
                "mode": "global",
                "source": "CVPR-2025 paper evaluation",
            },
        ),
        ReportedResult(
            claim_id="drvideo_moviechat_breakpoint_accuracy",
            metric_id="open_ended_accuracy_percent",
            value=56.4,
            qualifiers={
                "benchmark": "moviechat-1k",
                "mode": "breakpoint",
                "source": "CVPR-2025 paper evaluation",
            },
        ),
        ReportedResult(
            claim_id="drvideo_moviechat_breakpoint_score",
            metric_id="open_ended_quality_score_0_to_5",
            value=2.75,
            qualifiers={
                "benchmark": "moviechat-1k",
                "mode": "breakpoint",
                "source": "CVPR-2025 paper evaluation",
            },
        ),
        ReportedResult(
            claim_id="drvideo_videomme_long_without_subtitles",
            metric_id="multiple_choice_accuracy_percent",
            value=51.7,
            qualifiers={
                "benchmark": "video-mme",
                "duration": "long",
                "subtitles": False,
                "source": "CVPR-2025 paper evaluation",
            },
        ),
        ReportedResult(
            claim_id="drvideo_videomme_long_with_subtitles",
            metric_id="multiple_choice_accuracy_percent",
            value=71.7,
            qualifiers={
                "benchmark": "video-mme",
                "duration": "long",
                "subtitles": True,
                "source": "CVPR-2025 paper evaluation",
            },
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id="drvideo_long_video_baselines",
            description=(
                "Long-video retrieval and multimodal-agent baselines used by "
                "the CVPR 2025 paper on EgoSchema, MovieChat-1K and Video-MME."
            ),
            qualifiers={"source": "CVPR-2025 paper evaluation"},
        ),
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description=(
                "The CVPR paper reports Top-K=5 as the best/default retrieval "
                "setting, while the later official repository release hard-codes "
                "k=20 in get_relevant_frames. Both identities are retained and "
                "must not be silently conflated."
            ),
        ),
    ),
    blockers=(
        "MovieChat-1K and Video-MME paper cuts remain to be bound.",
        "Matched-result reproduction requires the paper-era model/API "
        "dependencies and benchmark media under artifact authority.",
    ),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_reproduction_current_surface_v1.py',),
)


__all__ = ["REPRODUCTION"]
