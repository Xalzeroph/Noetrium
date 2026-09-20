from __future__ import annotations
from noetrium_platform.research.reproduction import (
    ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef,
    ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle,
)

REPRODUCTION = ReproductionDefinition(
    package="watch_learn_cvpr2026",
    lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="watch-and-learn", title="Watch and Learn: Learning to Use Computers from Online Videos", paper_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Song_Watch_and_Learn_Learning_to_Use_Computers_from_Online_Videos_CVPR_2026_paper.html", year=2026, paper_revision="CVPR 2026 proceedings"),
    catalog=ReproductionCatalog(
        domains=("agent", "recent", "cvpr"),
        families=("watch_and_learn", "agentic_workflow"),
        priority=1,
        benchmark_ids=("osworld",),
        platform_pressure=("execution/workflow", "model/request", "benchmark", "experimentation/study", "evidence"),
        method_owned=(
            "task-aware tutorial-video retrieval",
            "inverse-dynamics UI trajectory annotation",
            "trajectory filtering",
            "ICL and SFT use of web-scale demonstrations",
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
        ReproductionAssetRef(ReproductionAssetKind.FIDELITY, "research/reproductions/watch_learn_cvpr2026/fidelity.py"),
        ReproductionAssetRef(ReproductionAssetKind.BENCHMARK, "research/reproductions/watch_learn_cvpr2026/benchmark.py"),
        ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM, "research/reproductions/watch_learn_cvpr2026/program.py"),
        ReproductionAssetRef(ReproductionAssetKind.STUDY, "research/reproductions/watch_learn_cvpr2026/study.py"),
    ),
    primary_executable="research/reproductions/watch_learn_cvpr2026/program.py",
    reported_results=(
        ReportedResult(claim_id="watch_learn_trajectory_count", metric_id="trajectory_count", value=53000, qualifiers={"bound": "greater-than", "source": "CVPR-2026 paper abstract"}),
        ReportedResult(claim_id="watch_learn_osworld_o3_gain", metric_id="successful_task_gain_count", value=15, qualifiers={"benchmark": "osworld", "base_successes": 83, "with_method_successes": 98, "source": "CVPR-2026 supplement Table 8"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="osworld_unconditioned_agents", description="Same computer-use agents without Watch-and-Learn trajectories", qualifiers={"source": "CVPR-2026 OSWorld evaluation"}),
    ),
    blockers=(
        "Matched data generation requires exact online video corpus snapshots and inverse-dynamics labeling artifacts.",
        "OSWorld runtime images and model checkpoints must match the evaluated configurations.",
    ),
    evidence_refs=(),
    scientific_tests=("tests/test_scientific_recent_2025_2026_wave_v1.py",),
)
__all__ = ["REPRODUCTION"]
