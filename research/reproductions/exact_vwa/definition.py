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
    package='exact_vwa',
    lifecycle=ReproductionLifecycle('protocol_bound'),
    identity=ReproductionIdentity(
        method_id='exact',
        title='ExACT: Teaching AI Agents to Explore with Reflective-MCTS and Exploratory Learning',
        paper_uri='https://arxiv.org/abs/2410.02052',
        year=2024,
        paper_revision='arXiv:2410.02052',
    ),
    catalog=ReproductionCatalog(
        domains=('planning-search', 'web-agents', 'reflection-self-correction', 'self-improvement'),
        families=('tree_search', 'reflection', 'web_agent', 'learning'),
        priority=2,
        benchmark_ids=('visualwebarena', 'osworld'),
        platform_pressure=('environment/web', 'environment/runtime', 'model/request', 'model/assignment', 'experimentation/study'),
        method_owned=('Reflective-MCTS', 'contrastive reflection', 'multi-agent debate value function', 'exploratory learning policy'),
        platform_owned=('model role binding', 'benchmark cut identity', 'environment lifecycle/reset', 'evidence and metrics'),
    ),
    assets=(
        ReproductionAssetRef(
            kind=ReproductionAssetKind('support'),
            path='research/reproductions/exact_vwa/branch.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('fidelity'),
            path='research/reproductions/exact_vwa/fidelity.py',
        ),
        ReproductionAssetRef(
            kind=ReproductionAssetKind('study'),
            path='research/reproductions/exact_vwa/study.py',
        ),
    ),
    reported_results=(
    ),
    reference_baselines=(
    ),
    deltas=(
        ReproductionDelta(
            kind=ReproductionDeltaKind('unresolved'),
            description='paper-era executable source cut preceding the later public VWA branch is unavailable',
        ),
    ),
    blockers=('public VWA executable history used here post-dates the paper', 'exact hosted GPT-4o and embedding deployment identities remain unresolved', 'matched browser/reset/replay infrastructure is not yet deployment-bound'),
    evidence_refs=(),
    scientific_tests=('tests/test_scientific_exact_vwa_v1.py',),
)

__all__ = ["REPRODUCTION"]
