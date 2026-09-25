from __future__ import annotations
from research.reproductions.contracts import (
    ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef,
    ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle,
)

REPRODUCTION = ReproductionDefinition(
    package="videoarm_cvpr2026",
    lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="videoarm", title="VideoARM: Agentic Reasoning over Hierarchical Memory for Long-Form Video Understanding", paper_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Yin_VideoARM_Agentic_Reasoning_over_Hierarchical_Memory_for_Long-Form_Video_Understanding_CVPR_2026_paper.html", year=2026, paper_revision="CVPR 2026 proceedings"),
    catalog=ReproductionCatalog(
        domains=("agent", "recent", "cvpr"),
        families=("videoarm", "agentic_workflow"),
        priority=1,
        benchmark_ids=("egoschema",),
        platform_pressure=("execution/workflow", "model/request", "benchmark", "experimentation/study", "evidence"),
        method_owned=(
            "observe-think-act-memorize control cycle",
            "hierarchical multimodal memory",
            "coarse-to-fine evidence tool routing",
            "bounded long-video agent reasoning",
        ),
        platform_owned=(
            "MethodProgram and Machine Journal execution authority",
            "model/provider transport",
            "benchmark cut identity",
            "experiment and measurement orchestration",
            "run evidence and provenance",
        ),
    ),
    assets=(
        ReproductionAssetRef(ReproductionAssetKind.FIDELITY, "research/reproductions/videoarm_cvpr2026/fidelity.py"),
        ReproductionAssetRef(ReproductionAssetKind.BENCHMARK, "research/reproductions/videoarm_cvpr2026/benchmark.py"),
        ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM, "research/reproductions/videoarm_cvpr2026/program.py"),
        ReproductionAssetRef(ReproductionAssetKind.STUDY, "research/reproductions/videoarm_cvpr2026/study.py"),
    ),
    primary_executable="research/reproductions/videoarm_cvpr2026/program.py",
    reported_results=(
        ReportedResult(claim_id="videoarm_egoschema_o3_gpt41", metric_id="multiple_choice_accuracy_percent", value=78.2, qualifiers={"benchmark": "egoschema", "controller": "o3", "multimodal_tool": "gpt-4.1", "source": "CVPR-2026 paper Table 1"}),
        ReportedResult(claim_id="videoarm_videomme_o3_gpt4o", metric_id="multiple_choice_accuracy_percent", value=82.8, qualifiers={"benchmark": "video-mme", "controller": "o3", "multimodal_tool": "gpt-4o", "source": "CVPR-2026 paper Table 1"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="dvd_video_agent", description="DVD long-video agent comparison reported by VideoARM", qualifiers={"egoschema_accuracy_percent": 76.6, "source": "CVPR-2026 paper Table 1"}),
    ),
    blockers=(
        "Matched execution requires immutable o3/GPT-4.x/Whisper provider identities and exact long-video assets.",
        "Video-MME, LongVideoBench, MLVU and LVBench remain additional benchmark authorities beyond the bound EgoSchema lane.",
    ),
    evidence_refs=(),
    scientific_tests=("tests/test_scientific_recent_2025_2026_wave_v1.py",),
)
__all__ = ["REPRODUCTION"]
