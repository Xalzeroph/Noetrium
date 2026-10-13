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
    package='generative_agents_memory',
    lifecycle=ReproductionLifecycle('protocol_bound'),
    identity=ReproductionIdentity(
        method_id='generative-agents',
        title='Generative Agents: Interactive Simulacra of Human Behavior',
        paper_uri='https://uist.acm.org/2023/proceedings/',
        year=2023,
        paper_revision=None,
    ),
    catalog=ReproductionCatalog(
        domains=('memory', 'multi-agent', 'social-economic'),
        families=('memory', 'reflection', 'planning', 'multi_agent'),
        priority=2,
        benchmark_ids=('generative-agents-smallville',),
        platform_pressure=('participant/agent', 'data/state', 'data/projection', 'data/query', 'execution/workflow', 'experimentation/study', 'observability/telemetry'),
        method_owned=('memory stream scoring', 'reflection synthesis', 'behavior planning semantics'),
        platform_owned=('multi-agent execution', 'durable state', 'semantic projection and query', 'study matrix', 'telemetry'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/generative_agents_memory/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('support'),
            path='research/reproductions/generative_agents_memory/retrieval.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('method_program'),
            path='research/reproductions/generative_agents_memory/program.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('study'),
            path='research/reproductions/generative_agents_memory/study.py',
        ),
    ),
    primary_executable="research/reproductions/generative_agents_memory/program.py",
    reported_results=(
        ReportedResult(
            claim_id="generative_agents_full_architecture_believability",
            metric_id="trueskill_mu",
            value=29.89,
            qualifiers={
                "evaluation": "interview-believability-ranking",
                "condition": "full-architecture",
                "participant_count": 100,
                "source": "UIST 2023 Figure 8",
            },
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id="generative_agents_ablations",
            description=(
                "UIST 2023 controlled believability ablations used to isolate "
                "reflection, planning and memory contributions."
            ),
            qualifiers={
                "no_reflection_trueskill_mu": 26.88,
                "no_reflection_or_planning_trueskill_mu": 25.64,
                "fully_ablated_trueskill_mu": 21.21,
                "human_crowdworker_trueskill_mu": 22.95,
                "source": "UIST 2023 Figure 8",
            },
        ),
    ),
    deltas=(
    ),
    blockers=('Matched UIST social-behavior results still require the exact paper-era Smallville persona/world snapshot, historical hosted model revision, and human believability rater assignment.',),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_generative_agents_retrieval_v1.py',),
)

__all__ = ["REPRODUCTION"]
