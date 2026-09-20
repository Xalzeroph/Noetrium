from __future__ import annotations
from noetrium_platform.research.reproduction import (
    ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef,
    ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle,
)

REPRODUCTION = ReproductionDefinition(
    package="openwebvoyager_acl2025",
    lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="openwebvoyager", title="OpenWebVoyager: Building Multimodal Web Agents via Iterative Real-World Exploration, Feedback and Optimization", paper_uri="https://aclanthology.org/2025.acl-long.1336/", year=2025, paper_revision="ACL 2025 proceedings"),
    catalog=ReproductionCatalog(
        domains=("agent", "recent", "acl"),
        families=("openwebvoyager", "agentic_workflow"),
        priority=1,
        benchmark_ids=("mind2web", "webvoyager"),
        platform_pressure=("execution/workflow", "model/request", "benchmark", "experimentation/study", "evidence"),
        method_owned=(
            "real-web multimodal exploration",
            "external-model feedback",
            "successful-trajectory filtering",
            "iterative self-improvement through retraining",
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
        ReproductionAssetRef(ReproductionAssetKind.FIDELITY, "research/reproductions/openwebvoyager_acl2025/fidelity.py"),
        ReproductionAssetRef(ReproductionAssetKind.BENCHMARK, "research/reproductions/openwebvoyager_acl2025/benchmark.py"),
        ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM, "research/reproductions/openwebvoyager_acl2025/program.py"),
        ReproductionAssetRef(ReproductionAssetKind.STUDY, "research/reproductions/openwebvoyager_acl2025/study.py"),
    ),
    primary_executable="research/reproductions/openwebvoyager_acl2025/program.py",
    reported_results=(
        ReportedResult(claim_id="openwebvoyager_webvoyager_final", metric_id="task_success_rate_percent", value=25.8, qualifiers={"benchmark": "webvoyager", "initial_percent": 19.9, "cycles": 3, "source": "ACL-2025 paper"}),
        ReportedResult(claim_id="openwebvoyager_mind2web_cross_task_final", metric_id="task_success_rate_percent", value=19.6, qualifiers={"benchmark": "mind2web", "initial_percent": 6.3, "cycles": 3, "source": "ACL-2025 paper"}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="openwebvoyager_initial_policy", description="Initial imitation-learning policy before iterative real-world self-improvement", qualifiers={"webvoyager_percent": 19.9, "mind2web_cross_task_percent": 6.3, "source": "ACL-2025 paper"}),
    ),
    blockers=(
        "Matched training requires exact imitation/exploration trajectory corpus, judge outputs and model checkpoint identities.",
        "Live web evaluation requires frozen website/environment state.",
    ),
    evidence_refs=(),
    scientific_tests=("tests/test_scientific_recent_2025_2026_wave_v1.py",),
)
__all__ = ["REPRODUCTION"]
