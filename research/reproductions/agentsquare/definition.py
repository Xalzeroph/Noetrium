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
        benchmark_ids=(\n            "webshop",\n            "alfworld",\n            "scienceworld",\n            "m3tooleval",\n            "travelplanner",\n            "agentboard-pddl",\n        ),
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
        ReproductionAssetRef(
            kind=ReproductionAssetKind("study"),
            path="research/reproductions/agentsquare/study.py",
        ),
    ),
    reported_results=(
        ReportedResult(
            claim_id="agentsquare_average_gain",
            metric_id="average_performance_gain_over_best_known_human_designs",
            value=17.2,
            qualifiers={"unit": "percent", "benchmarks": "six"},
        ),
        ReportedResult(
            claim_id="agentsquare_gpt4o_webshop",
            metric_id="webshop_reward",
            value=0.607,
            qualifiers={"model": "GPT-4o", "table": "1"},
        ),
        ReportedResult(
            claim_id="agentsquare_gpt4o_alfworld",
            metric_id="alfworld_success_rate",
            value=0.695,
            qualifiers={"model": "GPT-4o", "table": "1"},
        ),
        ReportedResult(
            claim_id="agentsquare_gpt4o_sciworld",
            metric_id="scienceworld_progress_rate",
            value=0.781,
            qualifiers={"model": "GPT-4o", "table": "1"},
        ),
        ReportedResult(
            claim_id="agentsquare_gpt4o_m3tool",
            metric_id="m3tool_success_rate",
            value=0.524,
            qualifiers={"model": "GPT-4o", "table": "1"},
        ),
        ReportedResult(
            claim_id="agentsquare_gpt4o_travelplanner",
            metric_id="travelplanner_constraint_pass_rate",
            value=0.583,
            qualifiers={"model": "GPT-4o", "table": "1"},
        ),
        ReportedResult(
            claim_id="agentsquare_gpt4o_pddl",
            metric_id="pddl_progress_rate",
            value=0.669,
            qualifiers={"model": "GPT-4o", "table": "1"},
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
        "the paper does not publish every benchmark-specific search sampling scope or random seed schedule",
        "the exact paper-era initial module archives are not all content-addressed in Noetrium",
        "matched results require the historical GPT-4o/GPT-3.5 service behavior used by the paper",
        "the later official ALFWorld search implementation post-dates the final paper and is executable-reference evidence rather than paper-era authority",
        "no matched six-benchmark AgentSquare execution evidence has yet been produced",
    ),
    evidence_refs=(),
    scientific_tests=(
        "tests/test_scientific_agentsquare_optimization_program_v1.py",
        "tests/test_scientific_agentsquare_webshop_cut_v1.py",
        "tests/test_scientific_agentsquare_six_benchmark_studies_v1.py",
    ),
)

__all__ = ["REPRODUCTION"]
