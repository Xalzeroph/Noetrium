from __future__ import annotations
from research.reproductions.contracts import (
    ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef,
    ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle,
)

REPRODUCTION = ReproductionDefinition(
    package="cer_acl2025",
    lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="contextual-experience-replay", title="Contextual Experience Replay for Self-Improvement of Language Agents", paper_uri="https://aclanthology.org/2025.acl-long.694/", year=2025, paper_revision="ACL 2025 proceedings"),
    catalog=ReproductionCatalog(
        domains=("agent", "recent", "acl"),
        families=("contextual_experience_replay", "agentic_workflow"),
        priority=1,
        benchmark_ids=("visualwebarena", "webarena"),
        platform_pressure=("execution/workflow", "model/request", "benchmark", "experimentation/study", "evidence"),
        method_owned=(
            "contextual experience replay",
            "successful-and-failed experience retrieval",
            "token-efficient test-time self-improvement",
            "experience-conditioned action context",
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
        ReproductionAssetRef(ReproductionAssetKind.FIDELITY, "research/reproductions/cer_acl2025/fidelity.py"),
        ReproductionAssetRef(ReproductionAssetKind.BENCHMARK, "research/reproductions/cer_acl2025/benchmark.py"),
        ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM, "research/reproductions/cer_acl2025/program.py"),
        ReproductionAssetRef(ReproductionAssetKind.STUDY, "research/reproductions/cer_acl2025/study.py"),
    ),
    primary_executable="research/reproductions/cer_acl2025/program.py",
    reported_results=(
        ReportedResult(claim_id="cer_visualwebarena", metric_id="task_success_rate_percent", value=31.9, qualifiers={"benchmark": "visualwebarena", "source": "ACL-2025 abstract"}),
        ReportedResult(claim_id="cer_webarena", metric_id="task_success_rate_percent", value=36.7, qualifiers={"benchmark": "webarena", "source": "ACL-2025 abstract"}),
        ReportedResult(claim_id="cer_webarena_relative_gain", metric_id="relative_success_gain_percent", value=51, qualifiers={"benchmark": "webarena", "comparison": "gpt-4o-agent-baseline", "source": "ACL-2025 abstract"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="gpt4o_web_agent", description="GPT-4o web-agent baseline without Contextual Experience Replay", qualifiers={"source": "ACL-2025 evaluation"}),
    ),
    blockers=(
        "Matched execution requires exact experience store initialization, retrieval parameters, prompts and web environment snapshots.",
        "Experience token-cost accounting must use the paper evaluator and tokenizer identities.",
    ),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_reproduction_current_surface_v1.py',),
)
__all__ = ["REPRODUCTION"]
