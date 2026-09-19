from __future__ import annotations

from noetrium_platform.research.reproduction import (
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
            "OptimizationMachine journal authority",
            "ResearchProgram hosting",
            "immutable executable-source provenance",
            "isolated generated-code execution",
            "random-decision evidence receipts",
            "measurement and artifact lineage",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/aflow/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("research_program"),
            path="research/reproductions/aflow/program.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("study"),
            path="research/reproductions/aflow/study.py",
        ),
    ),
    reported_results=(),
    reference_baselines=(),
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
    scientific_tests=(
        "tests/test_scientific_aflow_fidelity_v1.py",
        "tests/test_scientific_aflow_optimization_program_v1.py",
    ),
)

__all__ = ["REPRODUCTION"]
