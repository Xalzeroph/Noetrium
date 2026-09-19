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
    reported_results=(),
    reference_baselines=(),
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
    scientific_tests=(
        "tests/test_scientific_self_evolution_fidelity_v1.py",
        "tests/test_scientific_adas_method_program_v1.py",
        "tests/test_scientific_adas_mgsm_study_v1.py",
    ),
)

__all__ = ["REPRODUCTION"]
