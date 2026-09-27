from __future__ import annotations

from research.reproductions.contracts import (
    ReferenceBaseline,
    ReportedResult,
    ReproductionAssetKind,
    ReproductionAssetRef,
    ReproductionCatalog,
    ReproductionDefinition,
    ReproductionDelta,
    ReproductionDeltaKind,
    ReproductionIdentity,
    ReproductionLifecycle,
)

REPRODUCTION = ReproductionDefinition(
    package="aflow",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="aflow",
        title="AFlow: Automating Agentic Workflow Generation",
        paper_uri=(
            "https://proceedings.iclr.cc/paper_files/paper/2025/hash/"
            "5492ecbce4439401798dcd2c90be94cd-Abstract-Conference.html"
        ),
        year=2025,
        paper_revision=(
            "ICLR 2025 / MetaGPT paper-era source commit "
            "072839af7f75948d91d3784154128ab2456831f0"
        ),
    ),
    catalog=ReproductionCatalog(
        domains=("planning-search", "runtime-systems", "self-improvement"),
        families=(
            "agentic_workflow_generation",
            "meta_optimization",
            "workflow_search",
        ),
        priority=1,
        benchmark_ids=("humaneval",),
        platform_pressure=(
            "execution",
            "execution/research_program",
            "experimentation/workbench",
            "artifact/lineage",
            "model/request",
        ),
        method_owned=(
            "code-represented workflow search",
            "mixed weighted parent selection",
            "experience-conditioned workflow mutation",
            "validation-repeated workflow evaluation",
            "top-k convergence policy",
        ),
        platform_owned=(
            "Method-owned optimization component on the shared Machine journal",
            "Method-owned component hosting",
            "immutable executable-source provenance",
            "isolated generated-code execution",
            "random-decision evidence receipts",
            "measurement and artifact lineage",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("method_program"),
            path="research/reproductions/aflow/program.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/aflow/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("study"),
            path="research/reproductions/aflow/study.py",
        ),
    ),
    primary_executable="research/reproductions/aflow/program.py",
    reported_results=(
        ReportedResult(
            claim_id="aflow_average_sota_gain",
            metric_id="average_improvement_percent",
            value=5.7,
            qualifiers={"scope": "six-benchmark-average", "comparison": "state-of-the-art-baselines", "source": "ICLR-2025 paper"},
        ),
        ReportedResult(
            claim_id="aflow_automated_method_gain",
            metric_id="average_improvement_percent",
            value=19.5,
            qualifiers={"comparison": "existing-automated-workflow-methods", "source": "ICLR-2025 paper"},
        ),
        ReportedResult(
            claim_id="aflow_small_model_cost_fraction",
            metric_id="relative_inference_cost_percent",
            value=4.55,
            qualifiers={"comparison": "gpt-4o", "result": "smaller-model-workflow-can-outperform-gpt-4o", "source": "ICLR-2025 paper"},
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id="aflow_sota_agentic_workflows",
            description=(
                "State-of-the-art hand-designed and automated agentic workflow "
                "baselines used across the six AFlow benchmarks."
            ),
            qualifiers={"source": "ICLR-2025 paper evaluation"},
        ),
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind("substitution"),
            description=(
                "Paper-era AFlow uses ambient NumPy/Python RNG state for parent "
                "selection and log sampling. The reproduction preserves the exact "
                "sampling distribution but injects an explicit random-source port "
                "and journals each stochastic receipt so a Noetrium run can replay "
                "the realized trajectory."
            ),
        ),
        ReproductionDelta(
            kind=ReproductionDeltaKind("unresolved"),
            description=(
                "The paper-era initial-round workflows and six validation/test "
                "dataset files are distributed as external download archives and "
                "are not yet content-addressed Noetrium benchmark/artifact cuts."
            ),
        ),
    ),
    blockers=(
        "paper-era parent selection and failure-log sampling are not explicitly seeded in source",
        "paper-era initial-round workflow archive is not yet content-addressed in Noetrium",
        "paper-era HumanEval validation/test data archive is not yet content-addressed in Noetrium",
        "exact historical Claude-3-5-Sonnet-20240620 and GPT-4o-mini serving snapshots are not immutable public model artifacts",
        "no matched AFlow execution evidence has yet been produced",
    ),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_aflow_fidelity_v1.py',),
)

__all__ = ["REPRODUCTION"]
