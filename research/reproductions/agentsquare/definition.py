from __future__ import annotations

from noetrium_platform.research.reproduction import (
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
    package="agentsquare",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="agentsquare",
        title="AgentSquare: Automatic LLM Agent Search in Modular Design Space",
        paper_uri=(
            "https://proceedings.iclr.cc/paper_files/paper/2025/hash/"
            "0ae94013da7cd459402fd77874e09ee3-Abstract-Conference.html"
        ),
        year=2025,
        paper_revision="ICLR 2025 final paper",
    ),
    catalog=ReproductionCatalog(
        domains=("planning-search", "self-improvement", "agent-design"),
        families=(
            "automated_agent_design",
            "modular_agent_search",
            "module_evolution",
            "module_recombination",
        ),
        priority=1,
        benchmark_ids=("alfworld",),
        platform_pressure=(
            "execution/research_program",
            "experimentation/workbench",
            "participant/method",
            "memory",
            "capability",
            "artifact/lineage",
        ),
        method_owned=(
            "four-module planning/reasoning/tool-use/memory design space",
            "module evolution",
            "module recombination",
            "in-context performance predictor",
            "best-candidate benchmark evaluation loop",
        ),
        platform_owned=(
            "OptimizationMachine journal authority",
            "ResearchProgram hosting",
            "candidate execution/evaluation binding",
            "checkpoint and replay",
            "evidence and artifact lineage",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/agentsquare/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("research_program"),
            path="research/reproductions/agentsquare/program.py",
        ),
    ),
    reported_results=(
        ReportedResult(
            claim_id="agentsquare_average_gain",
            metric_id="average_performance_gain_over_best_known_human_designs",
            value=17.2,
            qualifiers={"unit": "percent", "benchmarks": "six"},
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id="best-known-human-designs",
            description="best known hand-crafted agent designs reported per benchmark",
            qualifiers={},
        ),
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind("substitution"),
            description=(
                "The full search implementation available in the official repository "
                "is later than the ICLR paper cut. Paper semantics are authoritative; "
                "the later official implementation is used only to freeze executable "
                "ALFWorld loop details such as the 10-iteration and 50-episode budget."
            ),
        ),
        ReproductionDelta(
            kind=ReproductionDeltaKind("substitution"),
            description=(
                "The released code mutates Python module files in-place and uses "
                "ambient process execution. The reproduction preserves module/archive "
                "and evaluation semantics while routing execution through explicit "
                "OptimizationMachine bindings and journaled evidence."
            ),
        ),
    ),
    blockers=(
        "the exact paper-era six benchmark search cuts and initial module archives are not all content-addressed in Noetrium",
        "matched results require the historical model-service revisions used by the paper",
        "the later official search implementation post-dates the final paper and cannot be treated as paper-era executable authority",
        "no matched six-benchmark AgentSquare execution evidence has yet been produced",
    ),
    evidence_refs=(),
    scientific_tests=(
        "tests/test_scientific_agentsquare_optimization_program_v1.py",
    ),
)

__all__ = ["REPRODUCTION"]
