from __future__ import annotations
from noetrium_platform.research.reproduction import (
    ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef,
    ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle,
)

REPRODUCTION = ReproductionDefinition(
    package="embodied_videoagent_iccv2025",
    lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="embodied-videoagent", title="Embodied VideoAgent: Persistent Memory from Egocentric Videos and Embodied Sensors Enables Dynamic Scene Understanding", paper_uri="https://openaccess.thecvf.com/content/ICCV2025/html/Fan_Embodied_VideoAgent_Persistent_Memory_from_Egocentric_Videos_and_Embodied_Sensors_ICCV_2025_paper.html", year=2025, paper_revision="ICCV 2025 proceedings"),
    catalog=ReproductionCatalog(
        domains=("agent", "recent", "iccv"),
        families=("embodied_videoagent", "agentic_workflow"),
        priority=1,
        benchmark_ids=("open-eqa", "envqa", "ego4d-vq3d"),
        platform_pressure=("execution/workflow", "model/request", "benchmark", "experimentation/study", "evidence"),
        method_owned=(
            "persistent object-centric 3D memory",
            "depth-and-pose object association",
            "VLM-triggered dynamic object-state update",
            "embodied memory retrieval for reasoning and planning",
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
        ReproductionAssetRef(ReproductionAssetKind.FIDELITY, "research/reproductions/embodied_videoagent_iccv2025/fidelity.py"),
        ReproductionAssetRef(ReproductionAssetKind.BENCHMARK, "research/reproductions/embodied_videoagent_iccv2025/benchmark.py"),
        ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM, "research/reproductions/embodied_videoagent_iccv2025/program.py"),
        ReproductionAssetRef(ReproductionAssetKind.STUDY, "research/reproductions/embodied_videoagent_iccv2025/study.py"),
    ),
    primary_executable="research/reproductions/embodied_videoagent_iccv2025/program.py",
    reported_results=(
        ReportedResult(claim_id="embodied_videoagent_vq3d_gain", metric_id="accuracy_gain_points", value=6.5, qualifiers={"benchmark": "ego4d-vq3d", "source": "ICCV-2025 abstract"}),
        ReportedResult(claim_id="embodied_videoagent_openeqa_gain", metric_id="accuracy_gain_points", value=2.6, qualifiers={"benchmark": "open-eqa", "source": "ICCV-2025 abstract"}),
        ReportedResult(claim_id="embodied_videoagent_envqa_gain", metric_id="accuracy_gain_points", value=15.3, qualifiers={"benchmark": "envqa", "source": "ICCV-2025 abstract"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="end_to_end_vlm_video_agents", description="End-to-end VLM and video-agent counterparts used by the ICCV paper", qualifiers={"source": "ICCV-2025 evaluation"}),
    ),
    blockers=(
        "OpenEQA, EnvQA and Ego4D-VQ3D are not yet canonical benchmark authorities in Noetrium.",
        "Matched execution additionally requires scene sensor streams, Habitat runtime identity and exact VLM checkpoints.",
    ),
    evidence_refs=(),
    scientific_tests=("tests/test_scientific_recent_2025_2026_wave_v1.py",),
)
__all__ = ["REPRODUCTION"]
