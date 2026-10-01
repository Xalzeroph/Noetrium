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
    package="adas_meta_agent_search",
    lifecycle=ReproductionLifecycle("protocol_bound"),
    identity=ReproductionIdentity(
        method_id="adas-meta-agent-search",
        title="Automated Design of Agentic Systems",
        paper_uri=(
            "https://proceedings.iclr.cc/paper_files/paper/2025/hash/"
            "36b7acf6f6010652b3f2a433774a66fe-Abstract-Conference.html"
        ),
        year=2025,
        paper_revision=(
            "ICLR 2025 / source commit "
            "2702bee8fefda42255efc5be9f60e3bd3db96ae4"
        ),
    ),
    catalog=ReproductionCatalog(
        domains=("self-improvement", "planning-search", "runtime-systems"),
        families=("agent_design", "meta_search", "self_improvement"),
        priority=1,
        benchmark_ids=("mgsm",),
        platform_pressure=(
            "participant/method",
            "execution",
            "experimentation/workbench",
            "experimentation/study",
            "artifact/lineage",
            "reliability/recovery",
        ),
        method_owned=(
            "archive-conditioned agent design search",
            "two-pass meta reflection",
            "candidate debug/regeneration policy",
            "candidate acceptance threshold",
        ),
        platform_owned=(
            "method host",
            "immutable candidate source publication",
            "isolated candidate execution",
            "benchmark/evaluator cut identity",
            "measurement/evidence lineage",
            "whole-cut study assignment",
            "recovery",
        ),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind("fidelity"),
            path="research/reproductions/adas_meta_agent_search/fidelity.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("method_program"),
            path="research/reproductions/adas_meta_agent_search/program.py",
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind("study"),
            path="research/reproductions/adas_meta_agent_search/study.py",
        ),
    ),
    primary_executable="research/reproductions/adas_meta_agent_search/program.py",
    reported_results=(
        ReportedResult(
            claim_id="adas_mgsm_top_agent_accuracy",
            metric_id="accuracy_percent",
            value=53.4,
            qualifiers={
                "benchmark": "MGSM",
                "agent": "Dynamic Role-Playing Architecture",
                "search_method": "Meta Agent Search",
                "source": "ICLR 2025 Table 1",
            },
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id="llm_debate_mgsm",
            description=(
                "Strongest hand-designed MGSM baseline in the ADAS Table 1 "
                "comparison."
            ),
            qualifiers={
                "accuracy_percent": 39.0,
                "source": "ICLR 2025 Table 1",
            },
        ),
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind("substitution"),
            description=(
                "The released MGSM search can regenerate source after the final "
                "failed candidate evaluation and then attach the previous fitness "
                "to that unexecuted source. The reproduction preserves the debug "
                "call but refuses stale source/measurement binding: an unexecuted "
                "debug candidate is skipped rather than admitted to the archive."
            ),
        ),
    ),
    blockers=(
        "Exact historical hosted GPT-4o-2024-05-13 and candidate "
        "GPT-3.5-Turbo serving snapshots are not immutable public model artifacts.",
    ),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_reproduction_current_surface_v1.py',),
)

__all__ = ["REPRODUCTION"]
