from __future__ import annotations

from noetrium_platform.research.reproduction import (
    ReferenceBaseline,
    ReportedResult,
    ReproductionAssetKind,
    ReproductionAssetRef,
    ReproductionCatalog,
    ReproductionDefinition,
    ReproductionIdentity,
    ReproductionLifecycle,
)

REPRODUCTION = ReproductionDefinition(
    package="agentless_swebench",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="agentless",
        title="Agentless: Demystifying LLM-based Software Engineering Agents",
        paper_uri=(
            "https://conf.researchr.org/details/fse-2025/"
            "fse-2025-research-papers/85/"
            "Demystifying-LLM-based-Software-Engineering-Agents"
        ),
        year=2025,
        paper_revision=(
            "FSE 2025 / official Agentless v1.5.0 "
            "b150f28465a77a81a7f4776384957a4271f5bd69"
        ),
    ),
    catalog=ReproductionCatalog(
        domains=("software-engineering",),
        families=("software_agent", "workflow", "repair", "validation"),
        priority=1,
        benchmark_ids=("swe-bench",),
        platform_pressure=(
            "environment/software",
            "execution/workflow",
            "experimentation/study",
            "artifact/lineage",
            "evaluation",
        ),
        method_owned=(
            "hierarchical file-to-symbol-to-edit localization",
            "multiple patch candidate sampling",
            "regression/reproduction-test validation policy",
            "validation-conditioned patch reranking",
        ),
        platform_owned=(
            "software workspace execution",
            "isolated verifier execution",
            "effect evidence",
            "artifact lineage",
            "model invocation",
            "study expansion",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/agentless_swebench/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("method_program"),
            path="research/reproductions/agentless_swebench/program.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("study"),
            path="research/reproductions/agentless_swebench/study.py",
        ),
    ),
    reported_results=(
        ReportedResult(
            claim_id="fse2025_swebench_lite_resolved",
            metric_id="resolved_rate",
            value=0.3267,
            qualifiers={"resolved_instances": "98", "task_count": "300"},
        ),
        ReportedResult(
            claim_id="fse2025_average_cost",
            metric_id="average_cost_usd",
            value=0.68,
            qualifiers={"benchmark": "SWE-bench Lite"},
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id="swe-agent",
            description=(
                "autonomous software-agent baseline contrasted with the fixed "
                "localization-repair-validation workflow"
            ),
            qualifiers={},
        ),
    ),
    deltas=(),
    blockers=(
        "matched execution requires immutable paper-era SWE-bench Lite dataset and harness bytes",
        "historical hosted model service revisions used for the reported FSE numbers are not content-addressable public artifacts",
        "exact released validation artifacts must be materialized under Artifact/Evidence authority before claim reproduction",
    ),
    evidence_refs=(),
    scientific_tests=(
        "tests/test_scientific_agentless_method_program_v1.py",
    ),
)

__all__ = ["REPRODUCTION"]
