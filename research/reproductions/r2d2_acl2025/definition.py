from __future__ import annotations
from research.reproductions.contracts import (
    ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef,
    ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle,
)

REPRODUCTION = ReproductionDefinition(
    package="r2d2_acl2025",
    lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="r2d2", title="R2D2: Remembering, Replaying and Dynamic Decision Making with a Reflective Agentic Memory", paper_uri="https://aclanthology.org/2025.acl-long.1464/", year=2025, paper_revision="ACL 2025 proceedings"),
    catalog=ReproductionCatalog(
        domains=("agent", "recent", "acl"),
        families=("r2d2", "agentic_workflow"),
        priority=1,
        benchmark_ids=("webarena",),
        platform_pressure=("execution/workflow", "model/request", "benchmark", "experimentation/study", "evidence"),
        method_owned=(
            "reflective replay memory",
            "dynamic web-environment map reconstruction",
            "navigation-error reflection",
            "memory-conditioned action selection",
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
        ReproductionAssetRef(ReproductionAssetKind.FIDELITY, "research/reproductions/r2d2_acl2025/fidelity.py"),
        ReproductionAssetRef(ReproductionAssetKind.BENCHMARK, "research/reproductions/r2d2_acl2025/benchmark.py"),
        ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM, "research/reproductions/r2d2_acl2025/program.py"),
        ReproductionAssetRef(ReproductionAssetKind.STUDY, "research/reproductions/r2d2_acl2025/study.py"),
    ),
    primary_executable="research/reproductions/r2d2_acl2025/program.py",
    reported_results=(
        ReportedResult(claim_id="r2d2_navigation_error_reduction", metric_id="navigation_error_reduction_percent", value=50, qualifiers={"benchmark": "webarena", "source": "ACL-2025 abstract"}),
        ReportedResult(claim_id="r2d2_completion_multiplier", metric_id="task_completion_rate_multiplier", value=3, qualifiers={"benchmark": "webarena", "source": "ACL-2025 abstract"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="existing_webarena_agents", description="Existing WebArena navigation agents from the ACL comparison", qualifiers={"source": "ACL-2025 evaluation"}),
    ),
    blockers=(
        "Matched WebArena execution requires paper-era website snapshots, replay-buffer prompts and model identity.",
        "Navigation-error accounting must be frozen to the paper evaluator implementation.",
    ),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_reproduction_current_surface_v1.py',),
)
__all__ = ["REPRODUCTION"]
