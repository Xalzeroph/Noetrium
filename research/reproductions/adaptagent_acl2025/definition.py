from __future__ import annotations
from research.reproductions.contracts import (
    ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef,
    ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle,
)

REPRODUCTION = ReproductionDefinition(
    package="adaptagent_acl2025",
    lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="adaptagent", title="AdaptAgent: Adapting Multimodal Web Agents with Few-Shot Learning from Human Demonstrations", paper_uri="https://aclanthology.org/2025.acl-long.1008/", year=2025, paper_revision="ACL 2025 proceedings"),
    catalog=ReproductionCatalog(
        domains=("agent", "recent", "acl"),
        families=("adaptagent", "agentic_workflow"),
        priority=1,
        benchmark_ids=("mind2web", "visualwebarena"),
        platform_pressure=("execution/workflow", "model/request", "benchmark", "experimentation/study", "evidence"),
        method_owned=(
            "few-shot website adaptation",
            "multimodal demonstration conditioning",
            "two-demonstration adaptation regime",
            "in-context and meta-adaptation variants",
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
        ReproductionAssetRef(ReproductionAssetKind.FIDELITY, "research/reproductions/adaptagent_acl2025/fidelity.py"),
        ReproductionAssetRef(ReproductionAssetKind.BENCHMARK, "research/reproductions/adaptagent_acl2025/benchmark.py"),
        ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM, "research/reproductions/adaptagent_acl2025/program.py"),
        ReproductionAssetRef(ReproductionAssetKind.STUDY, "research/reproductions/adaptagent_acl2025/study.py"),
    ),
    primary_executable="research/reproductions/adaptagent_acl2025/program.py",
    reported_results=(
        ReportedResult(claim_id="adaptagent_absolute_gain_min", metric_id="task_success_gain_points", value=3.36, qualifiers={"scope": "Mind2Web-and-VisualWebArena", "bound": "minimum", "source": "ACL-2025 abstract"}),
        ReportedResult(claim_id="adaptagent_absolute_gain_max", metric_id="task_success_gain_points", value=7.21, qualifiers={"scope": "Mind2Web-and-VisualWebArena", "bound": "maximum", "source": "ACL-2025 abstract"}),
        ReportedResult(claim_id="adaptagent_relative_gain_max", metric_id="relative_task_success_gain_percent", value=65.75, qualifiers={"scope": "Mind2Web-and-VisualWebArena", "bound": "maximum", "source": "ACL-2025 abstract"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="unadapted_multimodal_web_agents", description="Corresponding unadapted multimodal web agents", qualifiers={"source": "ACL-2025 evaluation"}),
    ),
    blockers=(
        "Matched runs require the exact human demonstration selections and paper-era checkpoint/model identities.",
        "VisualWebArena environment services must be frozen under immutable runtime identity.",
    ),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_reproduction_current_surface_v1.py',),
)
__all__ = ["REPRODUCTION"]
