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
    package='gats',
    lifecycle=ReproductionLifecycle('protocol_bound'),
    identity=ReproductionIdentity(
        method_id='gats',
        title='GATS: Graph-Augmented Tree Search with Layered World Models for Efficient Agent Planning',
        paper_uri='https://arxiv.org/abs/2607.08894',
        year=2026,
        paper_revision='arXiv:2607.08894v1',
    ),
    catalog=ReproductionCatalog(
        domains=('planning-search', 'world-models', 'evaluation-benchmarks'),
        families=('tree_search', 'world_model', 'synthetic_planning'),
        priority=1,
        benchmark_ids=('gats-synthetic',),
        platform_pressure=('experimentation/study', 'artifact/lineage'),
        method_owned=('UCB1 planning semantics', 'layered world-model semantics', 'stress-test direct-transition search implementation'),
        platform_owned=('source-lane provenance', 'benchmark task freezing', 'seed schedule identity', 'study expansion', 'execution evidence'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/gats/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('study'),
            path='research/reproductions/gats/study.py',
        ),
    ),
    reported_results=(
        ReportedResult(
            claim_id='paper_stress_gats_b20_success',
            metric_id='success_rate',
            value=100,
            qualifiers={'model_lane_id': None},
        ),
    ),
    reference_baselines=(
        ReferenceBaseline(
            baseline_id='greedy',
            description='greedy',
            qualifiers={},
        ),
        ReferenceBaseline(
            baseline_id='react',
            description='react',
            qualifiers={},
        ),
        ReferenceBaseline(
            baseline_id='lats_b10',
            description='lats_b10',
            qualifiers={},
        ),
        ReferenceBaseline(
            baseline_id='lats_b20',
            description='lats_b20',
            qualifiers={},
        ),
        ReferenceBaseline(
            baseline_id='gats_b10',
            description='gats_b10',
            qualifiers={},
        ),
        ReferenceBaseline(
            baseline_id='gats_b50',
            description='gats_b50',
            qualifiers={},
        ),
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind('unresolved'),
            description='main 100-task benchmark content must be materialized and frozen before source-matched execution',
        ),
        ReproductionDelta(
            kind=ReproductionDeltaKind('unresolved'),
            description='layered-world-model claims require the main evaluation lane rather than stress-script evidence',
        ),
    ),
    blockers=('main 100-task task generation is not seeded before random choice and shuffle in this source cut', 'stress-test GATSPlanner bypasses the paper layered world-model implementation and therefore cannot validate layered-world-model claims', 'no Noetrium execution evidence has yet been produced for the frozen stress Study'),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_gats_stress_v1.py',),
)

__all__ = ["REPRODUCTION"]
