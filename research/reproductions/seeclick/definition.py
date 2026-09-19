from __future__ import annotations

from noetrium_platform.research.reproduction import (
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
    package="seeclick",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="seeclick",
        title="SeeClick: Harnessing GUI Grounding for Advanced Visual GUI Agents",
        paper_uri="https://aclanthology.org/2024.acl-long.505/",
        year=2024,
        paper_revision="ACL 2024 final",
    ),
    catalog=ReproductionCatalog(
        domains=("gui-agent", "multimodal"),
        families=("gui_agent", "visual_grounding", "multimodal"),
        priority=1,
        benchmark_ids=("screenspot",),
        platform_pressure=(
            "model/request",
            "artifact/lineage",
            "experimentation/study",
            "environment/gui",
        ),
        method_owned=(
            "GUI grounding continual pre-training curriculum",
            "text-to-point and text-to-bbox grounding semantics",
            "normalized [0,1] GUI coordinate representation",
            "screenshot-only downstream GUI agent policy",
        ),
        platform_owned=(
            "multimodal image references",
            "model/checkpoint identity",
            "benchmark task and verifier identity",
            "measurement and evidence lineage",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/seeclick/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("support"),
            path="research/reproductions/seeclick/grounding.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("method_program"),
            path="research/reproductions/seeclick/program.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("study"),
            path="research/reproductions/seeclick/study.py",
        ),
    ),
    reported_results=(
        ReportedResult(
            claim_id="seeclick_screenspot_average",
            metric_id="grounding_accuracy_percent",
            value=53.4,
            qualifiers={"benchmark": "ScreenSpot", "model": "SeeClick"},
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id="cogagent-screenspot",
            description="CogAgent-18B on ScreenSpot as reported by the SeeClick release",
            qualifiers={"average_grounding_accuracy_percent": 47.4},
        ),
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description=(
                "The executable package reproduces the text-to-point grounding "
                "projection and ScreenSpot protocol. Exact continual pre-training "
                "of Qwen-VL-Chat remains a separately qualified model-training "
                "workload rather than MethodProgram runtime semantics."
            ),
        ),
    ),
    blockers=(
        "the exact ACL paper SeeClick checkpoint and LoRA/model closure must be materialized under immutable model identity",
        "the exact released ScreenSpot image/annotation cut must be frozen under Artifact authority",
        "matched downstream Mind2Web/AITW/MiniWob agent evaluation has not yet been bound",
    ),
    evidence_refs=(),
    scientific_tests=("tests/test_scientific_seeclick_v1.py",),
)

__all__ = ["REPRODUCTION"]
