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
        benchmark_ids=(),
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
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/drvideo/source.py",
        ),
    ),
    reported_results=(),
    reference_baselines=(),
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
        "Executable MethodProgram is being bound from the paper semantics.",
        "Exact EgoSchema, MovieChat-1K and Video-MME benchmark cuts and "
        "caption/model providers remain to be content-addressed.",
    ),
    evidence_refs=(),
    scientific_tests=("tests/test_scientific_drvideo_v1.py",),
)


__all__ = ["REPRODUCTION"]
