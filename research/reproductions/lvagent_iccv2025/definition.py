from __future__ import annotations
from noetrium_platform.research.reproduction import (
    ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef,
    ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle,
)

REPRODUCTION = ReproductionDefinition(
    package="lvagent_iccv2025",
    lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="lvagent", title="LVAgent: Long Video Understanding by Multi-Round Dynamical Collaboration of MLLM Agents", paper_uri="https://openaccess.thecvf.com/content/ICCV2025/html/Chen_LVAgent_Long_Video_Understanding_by_Multi-Round_Dynamical_Collaboration_of_MLLM_ICCV_2025_paper.html", year=2025, paper_revision="ICCV 2025 proceedings"),
    catalog=ReproductionCatalog(
        domains=("agent", "recent", "iccv"),
        families=("lvagent", "agentic_workflow"),
        priority=1,
        benchmark_ids=("egoschema",),
        platform_pressure=("execution/workflow", "model/request", "benchmark", "experimentation/study", "evidence"),
        method_owned=(
            "task-adaptive MLLM team selection",
            "long-video temporal retrieval",
            "multi-round reason exchange",
            "round-wise team reflection and optimization",
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
        ReproductionAssetRef(ReproductionAssetKind.FIDELITY, "research/reproductions/lvagent_iccv2025/fidelity.py"),
        ReproductionAssetRef(ReproductionAssetKind.BENCHMARK, "research/reproductions/lvagent_iccv2025/benchmark.py"),
        ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM, "research/reproductions/lvagent_iccv2025/program.py"),
        ReproductionAssetRef(ReproductionAssetKind.STUDY, "research/reproductions/lvagent_iccv2025/study.py"),
    ),
    primary_executable="research/reproductions/lvagent_iccv2025/program.py",
    reported_results=(
        ReportedResult(claim_id="lvagent_egoschema_three_round", metric_id="multiple_choice_accuracy_percent", value=82.7, qualifiers={"benchmark": "egoschema", "discussion_rounds": 3, "source": "ICCV-2025 paper Figure 7"}),
        ReportedResult(claim_id="lvagent_longvideobench_three_round", metric_id="multiple_choice_accuracy_percent", value=80, qualifiers={"benchmark": "longvideobench", "discussion_rounds": 3, "source": "ICCV-2025 paper Figure 7"}),
        ReportedResult(claim_id="lvagent_mlvu_three_round", metric_id="multiple_choice_accuracy_percent", value=83.8, qualifiers={"benchmark": "mlvu", "discussion_rounds": 3, "source": "ICCV-2025 paper Figure 7"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="lvagent_single_agent_pool", description="Individual MLLM agents before multi-agent collaboration", qualifiers={"longvideobench_best_single_percent": 69, "source": "ICCV-2025 paper agent-combination ablation"}),
    ),
    blockers=(
        "Matched execution requires exact LLaVA-Video and InternVL paper-era checkpoints and video sampling/retrieval artifacts.",
        "LongVideoBench, MLVU and Video-MME remain additional canonical benchmark bindings beyond EgoSchema.",
    ),
    evidence_refs=(),
    scientific_tests=("tests/test_scientific_recent_2025_2026_wave_v1.py",),
)
__all__ = ["REPRODUCTION"]
