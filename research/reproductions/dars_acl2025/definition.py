from __future__ import annotations
from research.reproductions.contracts import (
    ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef,
    ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle,
)

REPRODUCTION = ReproductionDefinition(
    package="dars_acl2025",
    lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="dars", title="DARS: Dynamic Action Re-Sampling to Enhance Coding Agent Performance by Adaptive Tree Traversal", paper_uri="https://aclanthology.org/2025.acl-long.973/", year=2025, paper_revision="ACL 2025 proceedings"),
    catalog=ReproductionCatalog(
        domains=("agent", "recent", "acl"),
        families=("dars", "agentic_workflow"),
        priority=1,
        benchmark_ids=("swe-bench",),
        platform_pressure=("execution/workflow", "model/request", "benchmark", "experimentation/study", "evidence"),
        method_owned=(
            "dynamic action re-sampling",
            "feedback-conditioned branch selection",
            "adaptive coding-agent tree traversal",
            "inference-time compute scaling",
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
        ReproductionAssetRef(ReproductionAssetKind.FIDELITY, "research/reproductions/dars_acl2025/fidelity.py"),
        ReproductionAssetRef(ReproductionAssetKind.BENCHMARK, "research/reproductions/dars_acl2025/benchmark.py"),
        ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM, "research/reproductions/dars_acl2025/program.py"),
        ReproductionAssetRef(ReproductionAssetKind.STUDY, "research/reproductions/dars_acl2025/study.py"),
    ),
    primary_executable="research/reproductions/dars_acl2025/program.py",
    reported_results=(
        ReportedResult(claim_id="dars_swebench_lite_pass_at_k", metric_id="pass_at_k_percent", value=55, qualifiers={"benchmark": "swe-bench-lite", "model": "claude-3.5-sonnet-v2", "source": "ACL-2025 abstract"}),
        ReportedResult(claim_id="dars_swebench_lite_pass_at_1", metric_id="pass_at_1_percent", value=47, qualifiers={"benchmark": "swe-bench-lite", "source": "ACL-2025 abstract"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="open_source_coding_agents", description="State-of-the-art open-source coding-agent frameworks", qualifiers={"source": "ACL-2025 evaluation"}),
    ),
    blockers=(
        "The exact SWE-bench Lite subset must be frozen as a named split over the canonical SWE-bench authority.",
        "Matched execution requires repository images, execution feedback and the paper-era Claude service identity.",
    ),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_reproduction_current_surface_v1.py',),
)
__all__ = ["REPRODUCTION"]
