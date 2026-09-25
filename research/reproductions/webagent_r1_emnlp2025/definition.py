from __future__ import annotations
from research.reproductions.contracts import (
    ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef,
    ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle,
)

REPRODUCTION = ReproductionDefinition(
    package="webagent_r1_emnlp2025",
    lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="webagent-r1", title="WebAgent-R1: Training Web Agents via End-to-End Multi-Turn Reinforcement Learning", paper_uri="https://aclanthology.org/2025.emnlp-main.401/", year=2025, paper_revision="EMNLP 2025 proceedings"),
    catalog=ReproductionCatalog(
        domains=("agent", "recent", "emnlp"),
        families=("webagent_r1", "agentic_workflow"),
        priority=1,
        benchmark_ids=("webarena",),
        platform_pressure=("execution/workflow", "model/request", "benchmark", "experimentation/study", "evidence"),
        method_owned=(
            "end-to-end multi-turn web-agent reinforcement learning",
            "behavior-cloning warm-up",
            "thinking-based web prompting",
            "interaction-count test-time scaling",
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
        ReproductionAssetRef(ReproductionAssetKind.FIDELITY, "research/reproductions/webagent_r1_emnlp2025/fidelity.py"),
        ReproductionAssetRef(ReproductionAssetKind.BENCHMARK, "research/reproductions/webagent_r1_emnlp2025/benchmark.py"),
        ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM, "research/reproductions/webagent_r1_emnlp2025/program.py"),
        ReproductionAssetRef(ReproductionAssetKind.STUDY, "research/reproductions/webagent_r1_emnlp2025/study.py"),
    ),
    primary_executable="research/reproductions/webagent_r1_emnlp2025/program.py",
    reported_results=(
        ReportedResult(claim_id="webagent_r1_qwen3b", metric_id="task_success_rate_percent", value=33.9, qualifiers={"benchmark": "webarena-lite", "base_percent": 6.1, "model": "qwen-2.5-3b", "source": "EMNLP-2025 abstract"}),
        ReportedResult(claim_id="webagent_r1_llama8b", metric_id="task_success_rate_percent", value=44.8, qualifiers={"benchmark": "webarena-lite", "base_percent": 8.5, "model": "llama-3.1-8b", "source": "EMNLP-2025 abstract"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="base_web_policies", description="Base Qwen-2.5-3B and Llama-3.1-8B web policies before WebAgent-R1 training", qualifiers={"source": "EMNLP-2025 evaluation"}),
    ),
    blockers=(
        "The exact WebArena-Lite subset must be frozen as a named split over canonical WebArena.",
        "Matched training requires behavior-cloning data, RL reward/configuration and exact model checkpoints.",
    ),
    evidence_refs=(),
    scientific_tests=("tests/test_scientific_recent_2025_2026_wave_v1.py",),
)
__all__ = ["REPRODUCTION"]
